"""Documenti: DOCX, PDF, Markdown, TXT, HTML.

Architettura: l'HTML fa da "hub". DOCX/MD/TXT/HTML → HTML → (PDF | DOCX | MD | TXT).
Un piccolo parser trasforma l'HTML in blocchi (titoli, paragrafi, elenchi, tabelle…)
da cui si scrivono DOCX, Markdown e testo semplice.
"""
from __future__ import annotations

import base64
import html as htmllib
import io
import os
import re
import shutil
import tempfile
from html.parser import HTMLParser

import formats
import images
from common import ConversionError, Ctx, atomic, fitz_mod, read_text, write_text

BASE_CSS = """
body { font-family: sans-serif; font-size: 11pt; color: #111111; }
h1 { font-size: 21pt; margin: 14pt 0 6pt 0; }
h2 { font-size: 16pt; margin: 12pt 0 5pt 0; }
h3 { font-size: 13pt; margin: 10pt 0 4pt 0; }
h4, h5, h6 { font-size: 11pt; margin: 8pt 0 3pt 0; }
p { margin: 0 0 7pt 0; }
ul, ol { margin: 0 0 7pt 0; }
pre { font-family: monospace; font-size: 9pt; margin: 0 0 7pt 0; background-color: #f1f3f5; }
code, tt, kbd, samp { font-family: monospace; }
table { border-collapse: collapse; margin: 4pt 0 10pt 0; }
td, th { border: 0.6pt solid #999999; padding: 3pt 5pt; vertical-align: top; }
th { background-color: #e6ecf3; font-weight: bold; }
blockquote { margin: 0 0 7pt 16pt; color: #444444; }
a { color: #1a56c4; }
"""

_DATA_IMG = re.compile(r'src\s*=\s*"data:(image/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)"', re.I)


# ═══════════════════════════ HTML → PDF ═══════════════════════════
def html_to_pdf(html_text: str, dest: str, base_dir: str | None = None,
                landscape: bool = False, css: str = BASE_CSS, margin: float = 42):
    fz = fitz_mod()
    arch = fz.Archive(base_dir) if base_dir and os.path.isdir(base_dir) else fz.Archive()
    counter = [0]

    def repl(m):
        counter[0] += 1
        ext = m.group(1).split("/")[-1].replace("jpeg", "jpg").replace("svg+xml", "svg")
        name = f"_cfimg{counter[0]}.{ext}"
        try:
            arch.add(base64.b64decode(re.sub(r"\s+", "", m.group(2))), name)
        except Exception:
            return 'src=""'
        return f'src="{name}"'

    html_text = _DATA_IMG.sub(repl, html_text)
    rect = fz.paper_rect("a4-l" if landscape else "a4")
    where = rect + (margin, margin, -margin, -margin)
    try:
        story = fz.Story(html=html_text, user_css=css, em=11, archive=arch)
        writer = fz.DocumentWriter(dest)
        more, empty_runs, pages = 1, 0, 0
        while more:
            dev = writer.begin_page(rect)
            more, filled = story.place(where)
            story.draw(dev)
            writer.end_page()
            pages += 1
            empty_runs = empty_runs + 1 if fz.Rect(filled).is_empty else 0
            if empty_runs >= 2 or pages > 3000:
                raise ConversionError("Il documento contiene un elemento troppo grande per la pagina.")
        writer.close()
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(f"Impossibile creare il PDF ({exc}).") from exc


# ═══════════════════════════ HTML → blocchi ═══════════════════════════
_BLOCK_TAGS = {"p", "div", "section", "article", "header", "footer", "nav", "main", "aside",
               "figure", "figcaption", "dl", "dt", "dd", "address", "center", "summary", "details"}
_SKIP = {"script", "style", "head", "title", "template", "noscript"}


class _Parser(HTMLParser):
    def __init__(self, base_dir=None):
        super().__init__(convert_charrefs=True)
        self.base_dir = base_dir
        self.blocks = []
        self.runs = []
        self.kind = ("p",)
        self.fmt = {"b": 0, "i": 0, "u": 0, "code": 0}
        self.href = []
        self.lists = []
        self.in_pre = False
        self.pre = []
        self.skip = 0
        self.table = None
        self.row = None
        self.cell = None
        self.cell_is_th = False
        self.quote = 0

    # ── helpers ──
    def _target(self):
        return self.cell if self.cell is not None else self.runs

    def _add(self, text):
        if not text:
            return
        run = (text, bool(self.fmt["b"]), bool(self.fmt["i"]), bool(self.fmt["u"]),
               bool(self.fmt["code"]), self.href[-1] if self.href else None)
        self._target().append(run)

    @staticmethod
    def _clean(runs):
        out = []
        for r in runs:
            if out and out[-1][1:] == r[1:]:
                out[-1] = (out[-1][0] + r[0],) + r[1:]
            else:
                out.append(r)
        # niente spazi a inizio/fine blocco
        while out and not out[0][0].strip(" \t\r\n\xa0") and out[0][0] != "\n":
            out.pop(0)
        if out:
            out[0] = (out[0][0].lstrip(" \t\r"),) + out[0][1:]
        while out and not out[-1][0].strip(" \t\r\n\xa0"):
            out.pop()
        if out:
            out[-1] = (out[-1][0].rstrip(" \t\r\n"),) + out[-1][1:]
        return [r for r in out if r[0]]

    def flush(self):
        if self.cell is not None:
            return
        runs = self._clean(self.runs)
        self.runs = []
        if not runs or not "".join(r[0] for r in runs).strip("\xa0 \n"):
            return
        k = self.kind
        b = {"runs": runs, "quote": self.quote > 0}
        if k[0] == "h":
            b.update(t="h", l=k[1])
        elif k[0] == "li":
            b.update(t="li", depth=k[1], ord=k[2], n=k[3])
        else:
            b.update(t="p")
        self.blocks.append(b)

    def _load_img(self, src):
        if not src:
            return None
        try:
            if src.startswith("data:"):
                return base64.b64decode(src.split(",", 1)[1])
            if self.base_dir and not re.match(r"^[a-z]+://", src, re.I):
                p = os.path.join(self.base_dir, src.split("?")[0].split("#")[0])
                p = os.path.normpath(p.replace("%20", " "))
                if os.path.isfile(p) and os.path.getsize(p) < 30_000_000:
                    with open(p, "rb") as f:
                        return f.read()
        except Exception:
            pass
        return None

    # ── eventi ──
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in _SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.flush(); self.kind = ("h", int(tag[1]))
        elif tag in _BLOCK_TAGS:
            if self.kind[0] == "li":
                if self.runs and not self.cell:
                    self._add(" ")
            else:
                self.flush(); self.kind = ("p",)
        elif tag == "blockquote":
            self.flush(); self.quote += 1
        elif tag in ("ul", "ol"):
            self.flush(); self.lists.append([tag == "ol", 0])
        elif tag == "li":
            self.flush()
            if not self.lists:
                self.lists.append([False, 0])
            self.lists[-1][1] += 1
            self.kind = ("li", len(self.lists) - 1, self.lists[-1][0], self.lists[-1][1])
        elif tag == "br":
            self._add("\n") if not self.in_pre else self.pre.append("\n")
        elif tag in ("b", "strong"):
            self.fmt["b"] += 1
        elif tag in ("i", "em", "cite", "dfn", "var"):
            self.fmt["i"] += 1
        elif tag in ("u", "ins"):
            self.fmt["u"] += 1
        elif tag in ("code", "kbd", "samp", "tt"):
            self.fmt["code"] += 1
        elif tag == "a":
            self.href.append(a.get("href") if a.get("href", "").startswith(("http", "mailto:")) else None)
        elif tag == "pre":
            self.flush(); self.in_pre = True; self.pre = []
        elif tag == "table":
            self.flush(); self.table = {"rows": [], "head": False}
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.table is not None:
            if self.row is None:
                self.row = []
            self.cell = []
            self.cell_is_th = tag == "th"
        elif tag == "img" and self.cell is None:
            self.flush()
            data = self._load_img(a.get("src", ""))
            if data:
                self.blocks.append({"t": "img", "data": data})
        elif tag == "hr":
            self.flush(); self.blocks.append({"t": "hr"})

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if re.fullmatch(r"h[1-6]", tag) or tag in _BLOCK_TAGS:
            if self.kind[0] != "li" or re.fullmatch(r"h[1-6]", tag):
                self.flush(); self.kind = ("p",)
        elif tag == "blockquote":
            self.flush(); self.quote = max(0, self.quote - 1)
        elif tag in ("ul", "ol"):
            self.flush()
            if self.lists:
                self.lists.pop()
            self.kind = ("p",)
        elif tag == "li":
            self.flush(); self.kind = ("p",)
        elif tag in ("b", "strong"):
            self.fmt["b"] = max(0, self.fmt["b"] - 1)
        elif tag in ("i", "em", "cite", "dfn", "var"):
            self.fmt["i"] = max(0, self.fmt["i"] - 1)
        elif tag in ("u", "ins"):
            self.fmt["u"] = max(0, self.fmt["u"] - 1)
        elif tag in ("code", "kbd", "samp", "tt"):
            self.fmt["code"] = max(0, self.fmt["code"] - 1)
        elif tag == "a":
            if self.href:
                self.href.pop()
        elif tag == "pre":
            text = "".join(self.pre).strip("\n")
            self.in_pre = False
            if text.strip():
                self.blocks.append({"t": "pre", "text": text})
        elif tag in ("td", "th") and self.cell is not None:
            cell = self._clean(self.cell)
            if self.cell_is_th and not self.table["rows"]:
                self.table["head"] = True
            self.row.append(cell)
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            if self.row:
                self.table["rows"].append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            if self.row:
                self.table["rows"].append(self.row)
            self.row = None
            rows = self.table["rows"]
            if rows:
                w = max(len(r) for r in rows)
                rows = [r + [[]] * (w - len(r)) for r in rows]
                self.blocks.append({"t": "table", "rows": rows, "head": self.table["head"]})
            self.table = None
            self.cell = None

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_pre:
            self.pre.append(data)
            return
        self._add(re.sub(r"[ \t\r\n\f]+", " ", data))

    def close(self):
        super().close()
        self.flush()


def parse_blocks(html_text: str, base_dir: str | None = None) -> list:
    p = _Parser(base_dir)
    p.feed(html_text)
    p.close()
    return p.blocks


def _text(runs) -> str:
    return "".join(r[0] for r in runs)


# ═══════════════════════════ blocchi → TXT / MD ═══════════════════════════
def blocks_to_txt(blocks) -> str:
    out, prev = [], None
    for b in blocks:
        t = b["t"]
        if t == "h" or t == "p":
            line = _text(b["runs"])
        elif t == "li":
            ind = "  " * b["depth"]
            mark = f'{b["n"]}. ' if b["ord"] else "- "
            line = ind + mark + _text(b["runs"]).replace("\n", "\n" + ind + "  ")
        elif t == "table":
            line = "\n".join("\t".join(_text(c).replace("\n", " ") for c in row) for row in b["rows"])
        elif t == "pre":
            line = b["text"]
        elif t == "hr":
            line = "-" * 40
        else:
            continue
        same = t == "li" and prev == ("li", b["ord"])
        out.append(("\n" if same else "\n\n") + line)
        prev = (t, b.get("ord"))
    return "".join(out).lstrip("\n") + "\n"


def _md_esc(s: str) -> str:
    return re.sub(r"([\\`*_\[\]<>])", r"\\\1", s)


def _md_runs(runs) -> str:
    s = ""
    for text, bold, ital, _u, code, href in runs:
        if text == "\n":
            s += "  \n"
            continue
        if code:
            s += "`" + text.replace("`", "'") + "`"
            continue
        t = _md_esc(text)
        core = t.strip()
        if core:
            lead, trail = t[:len(t) - len(t.lstrip())], t[len(t.rstrip()):]
            if bold and ital:
                core = f"***{core}***"
            elif bold:
                core = f"**{core}**"
            elif ital:
                core = f"*{core}*"
            if href:
                core = f"[{core}]({href})"
            t = lead + core + trail
        s += t
    return re.sub(r"^(\s*)([#>+\-]|\d+[.)])(\s)", r"\1\\\2\3", s)


def blocks_to_md(blocks) -> str:
    out, prev = [], None
    for b in blocks:
        t = b["t"]
        q = "> " if b.get("quote") else ""
        if t == "h":
            line = "#" * min(b["l"], 6) + " " + _md_runs(b["runs"]).replace("\n", " ")
        elif t == "p":
            line = q + _md_runs(b["runs"])
        elif t == "li":
            ind = "  " * b["depth"]
            mark = f'{b["n"]}. ' if b["ord"] else "- "
            line = ind + mark + _md_runs(b["runs"]).replace("\n", "\n" + ind + "  ")
        elif t == "table":
            rows = [[_md_runs(c).replace("|", "\\|").replace("\n", "<br>") or " " for c in r]
                    for r in b["rows"]]
            lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * len(rows[0])]
            lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            line = "\n".join(lines)
        elif t == "pre":
            line = "```\n" + b["text"] + "\n```"
        elif t == "hr":
            line = "---"
        else:
            continue
        same = t == "li" and prev == ("li", b["ord"])
        out.append(("\n" if same else "\n\n") + line)
        prev = (t, b.get("ord"))
    return "".join(out).lstrip("\n") + "\n"


# ═══════════════════════════ blocchi → DOCX ═══════════════════════════
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _hyperlink(par, text, url, bold, ital):
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    rid = par.part.relate_to(url, RT.HYPERLINK, is_external=True)
    h = OxmlElement("w:hyperlink")
    h.set(qn("r:id"), rid)
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    for tag, val in (("w:color", "0563C1"), ("w:u", "single")):
        e = OxmlElement(tag)
        e.set(qn("w:val"), val)
        rpr.append(e)
    if bold:
        rpr.append(OxmlElement("w:b"))
    if ital:
        rpr.append(OxmlElement("w:i"))
    r.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    r.append(t)
    h.append(r)
    par._p.append(h)


def _fill(par, runs, force_bold=False):
    from docx.shared import Pt
    for text, bold, ital, und, code, href in runs:
        text = _CTRL.sub("", text)
        if text == "\n":
            par.add_run().add_break()
            continue
        if href:
            _hyperlink(par, text, href, bold or force_bold, ital)
            continue
        r = par.add_run(text)
        r.bold = True if (bold or force_bold) else None
        r.italic = True if ital else None
        r.underline = True if und else None
        if code:
            r.font.name = "Consolas"
            r.font.size = Pt(10)


def _hr(par):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    ppr = par._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", "999999")):
        bottom.set(qn(k), v)
    bdr.append(bottom)
    ppr.append(bdr)


def blocks_to_docx(blocks, dest: str):
    from docx import Document
    from docx.shared import Inches, Pt
    d = Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(11)
    for b in blocks:
        t = b["t"]
        if t == "h":
            p = d.add_heading(level=min(b["l"], 9))
            _fill(p, b["runs"])
        elif t == "p":
            try:
                p = d.add_paragraph(style="Quote" if b.get("quote") else None)
            except KeyError:
                p = d.add_paragraph()
            _fill(p, b["runs"])
        elif t == "li":
            depth = min(b["depth"], 2)
            if b["ord"]:
                p = d.add_paragraph()
                p.paragraph_format.left_indent = Inches(0.3 * (depth + 1))
                p.paragraph_format.first_line_indent = Inches(-0.25)
                p.add_run(f'{b["n"]}.\t')
            else:
                p = d.add_paragraph(style="List Bullet" + ("" if depth == 0 else f" {depth + 1}"))
            _fill(p, b["runs"])
        elif t == "table":
            rows = b["rows"]
            tbl = d.add_table(rows=len(rows), cols=len(rows[0]))
            tbl.style = "Table Grid"
            for ri, row in enumerate(rows):
                for ci, cell in enumerate(row):
                    c = tbl.cell(ri, ci)
                    _fill(c.paragraphs[0], cell, force_bold=(b["head"] and ri == 0))
            d.add_paragraph()
        elif t == "pre":
            p = d.add_paragraph()
            lines = _CTRL.sub("", b["text"]).split("\n")
            for i, line in enumerate(lines):
                r = p.add_run(line)
                r.font.name = "Consolas"
                r.font.size = Pt(9.5)
                if i < len(lines) - 1:
                    r.add_break()
        elif t == "hr":
            _hr(d.add_paragraph())
        elif t == "img":
            try:
                from PIL import Image
                with Image.open(io.BytesIO(b["data"])) as im:
                    w_px = im.size[0]
                d.add_picture(io.BytesIO(b["data"]), width=Inches(min(6.0, max(0.5, w_px / 96))))
            except Exception:
                pass
    if not d.paragraphs and not d.tables:
        d.add_paragraph("")
    d.save(dest)


# ═══════════════════════════ sorgenti → HTML ═══════════════════════════
def wrap_html(body: str, title: str = "") -> str:
    return ("<!doctype html>\n<html lang=\"it\"><head><meta charset=\"utf-8\">"
            f"<title>{htmllib.escape(title)}</title>\n<style>"
            "body{font-family:Segoe UI,Arial,sans-serif;max-width:46em;margin:2em auto;padding:0 1em;line-height:1.5}"
            "pre{background:#f1f3f5;padding:.6em;overflow:auto}table{border-collapse:collapse}"
            "td,th{border:1px solid #bbb;padding:4px 8px}img{max-width:100%}"
            "</style></head><body>\n" + body + "\n</body></html>\n")


def txt_to_html(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paras = []
    for chunk in re.split(r"\n{2,}", text.strip("\n")):
        lines = []
        for line in chunk.split("\n"):
            m = re.match(r"^( +)", line)
            lines.append("&nbsp;" * len(m.group(1)) + htmllib.escape(line[len(m.group(1)):]) if m
                         else htmllib.escape(line))
        paras.append("<p>" + "<br>".join(lines) + "</p>")
    return "\n".join(paras)


def md_to_html(text: str) -> str:
    try:
        import markdown
    except ImportError as exc:
        raise ConversionError("Manca il modulo Markdown (pip install Markdown).") from exc
    return markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])


def _num_is_ordered(doc, num_id, ilvl) -> bool:
    try:
        root = doc.part.numbering_part.element
        abs_id = root.xpath(f'w:num[@w:numId="{num_id}"]/w:abstractNumId/@w:val')[0]
        fmt = root.xpath(f'w:abstractNum[@w:abstractNumId="{abs_id}"]/w:lvl[@w:ilvl="{ilvl}"]/w:numFmt/@w:val')
        return bool(fmt) and fmt[0] not in ("bullet", "none")
    except Exception:
        return False


def docx_to_html(path: str) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    try:
        d = Document(path)
    except Exception as exc:
        raise ConversionError("File Word non valido, danneggiato o protetto da password.") from exc

    def inline(par) -> str:
        out = []
        try:
            items = list(par.iter_inner_content())
        except AttributeError:
            items = list(par.runs)
        for it in items:
            if hasattr(it, "url"):  # collegamento ipertestuale
                txt = htmllib.escape(it.text)
                url = it.url or ""
                out.append(f'<a href="{htmllib.escape(url)}">{txt}</a>' if url.startswith(("http", "mailto:")) else txt)
                continue
            r = it
            for rid in r._r.xpath(".//a:blip/@r:embed"):
                try:
                    part = d.part.related_parts[rid]
                    if part.content_type in ("image/png", "image/jpeg", "image/gif", "image/bmp", "image/webp"):
                        b64 = base64.b64encode(part.blob).decode()
                        out.append(f'<img src="data:{part.content_type};base64,{b64}">')
                except Exception:
                    pass
            txt = htmllib.escape(r.text or "").replace("\n", "<br>").replace("\t", "&emsp;")
            if not txt:
                continue
            style = []
            try:
                if r.font.color is not None and r.font.color.rgb is not None:
                    style.append(f"color:#{r.font.color.rgb}")
                if r.font.size:
                    style.append(f"font-size:{r.font.size.pt:g}pt")
            except Exception:
                pass
            if style:
                txt = f'<span style="{";".join(style)}">{txt}</span>'
            if r.bold or (r.style is not None and r.style.name == "Strong"):
                txt = f"<b>{txt}</b>"
            if r.italic or (r.style is not None and r.style.name == "Emphasis"):
                txt = f"<i>{txt}</i>"
            if r.underline:
                txt = f"<u>{txt}</u>"
            out.append(txt)
        return "".join(out)

    parts, stack = [], []

    def close_to(n):
        while len(stack) > n:
            parts.append(f"</{stack.pop()}>")

    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(el, d)
            sname = (p.style.name if p.style is not None else "") or ""
            ppr = p._p.pPr
            numpr = ppr.numPr if ppr is not None else None
            if numpr is not None and numpr.numId is not None and numpr.numId.val != 0 or "List" in sname:
                ilvl = int(numpr.ilvl.val) if numpr is not None and numpr.ilvl is not None else 0
                if numpr is not None and numpr.numId is not None:
                    ordered = _num_is_ordered(d, numpr.numId.val, ilvl)
                else:
                    ordered = "Number" in sname
                want = "ol" if ordered else "ul"
                close_to(ilvl + 1)
                if len(stack) == ilvl + 1 and stack[-1] != want:
                    close_to(ilvl)
                while len(stack) < ilvl + 1:
                    stack.append(want)
                    parts.append(f"<{want}>")
                parts.append(f"<li>{inline(p)}</li>")
                continue
            close_to(0)
            body = inline(p)
            m = re.match(r"Heading (\d)", sname)
            if m:
                parts.append(f"<h{m.group(1)}>{body}</h{m.group(1)}>")
            elif sname == "Title":
                parts.append(f"<h1>{body}</h1>")
            elif sname == "Subtitle":
                parts.append(f"<h2>{body}</h2>")
            else:
                align = ""
                try:
                    a = int(p.alignment) if p.alignment is not None else None
                    align = {1: "center", 2: "right", 3: "justify"}.get(a, "")
                except Exception:
                    pass
                st = f' style="text-align:{align}"' if align else ""
                parts.append(f"<p{st}>{body or '&nbsp;'}</p>")
        elif tag == "tbl":
            close_to(0)
            t = Table(el, d)
            rows = ["<table>"]
            for row in t.rows:
                cells, last = [], None
                for c in row.cells:
                    if last is not None and c._tc is last:
                        continue
                    last = c._tc
                    inner = "<br>".join(inline(p) for p in c.paragraphs if p.text.strip() or p.runs)
                    cells.append(f"<td>{inner or '&nbsp;'}</td>")
                rows.append("<tr>" + "".join(cells) + "</tr>")
            rows.append("</table>")
            parts.append("".join(rows))
    close_to(0)
    return "\n".join(parts)


def source_to_html(ctx: Ctx):
    """Ritorna (html_frammento, cartella_base)."""
    k = ctx.key
    if k == "docx":
        return docx_to_html(ctx.source), None
    if k == "md":
        return md_to_html(read_text(ctx.source)), None
    if k == "txt":
        return txt_to_html(read_text(ctx.source)), None
    if k == "html":
        return read_text(ctx.source), os.path.dirname(os.path.abspath(ctx.source))
    raise ConversionError("Formato di documento non supportato.")


# ═══════════════════════════ PDF come sorgente ═══════════════════════════
def _open_pdf(path):
    fz = fitz_mod()
    try:
        doc = fz.open(path)
    except Exception as exc:
        raise ConversionError("PDF non valido o danneggiato.") from exc
    if doc.needs_pass:
        doc.close()
        raise ConversionError("Il PDF è protetto da password.")
    return doc


def pdf_to_docx(ctx: Ctx) -> list:
    _open_pdf(ctx.source).close()
    try:
        from pdf2docx import Converter
    except ImportError as exc:
        raise ConversionError("Manca il modulo pdf2docx (pip install pdf2docx).") from exc
    dest = ctx.out_file("docx")
    with atomic(dest) as tmp:
        cv = Converter(ctx.source)
        try:
            cv.convert(tmp)
        finally:
            cv.close()
    return [dest]


def pdf_to_text(ctx: Ctx) -> list:
    doc = _open_pdf(ctx.source)
    try:
        pages = [p.get_text("text") for p in doc]
        if not any(t.strip() for t in pages):
            raise ConversionError("Il PDF contiene solo immagini (scansione): senza OCR non c'è testo da estrarre.")
        t = ctx.target
        if t == "txt":
            content = "\n\n".join(x.strip("\n") for x in pages) + "\n"
        else:
            xhtml = "\n".join(p.get_text("xhtml") for p in doc)
            if t == "html":
                content = wrap_html(re.sub(r"(?is)<!DOCTYPE.*?<body[^>]*>|</body>.*", "", xhtml), ctx.stem)
            else:
                content = blocks_to_md(parse_blocks(xhtml))
        dest = ctx.out_file(t)
        with atomic(dest) as tmp:
            write_text(tmp, content)
        return [dest]
    finally:
        doc.close()


# ═══════════════════════════ emissione ═══════════════════════════
def _pdf_via_temp(ctx: Ctx, build) -> list:
    """Per i target immagine: crea un PDF temporaneo e lo rasterizza pagina per pagina."""
    tmpd = tempfile.mkdtemp(prefix="cf-")
    try:
        pdf = os.path.join(tmpd, "tmp.pdf")
        build(pdf)
        return images.pdf_pages_to_images(ctx, pdf)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def emit_from_html(ctx: Ctx, html_text: str, base_dir=None, landscape=False, css=BASE_CSS) -> list:
    t = ctx.target
    ctx.check()
    if t == "pdf":
        dest = ctx.out_file("pdf")
        with atomic(dest) as tmp:
            html_to_pdf(html_text, tmp, base_dir, landscape, css)
        return [dest]
    if t in images.PIL_NAME:
        return _pdf_via_temp(ctx, lambda p: html_to_pdf(html_text, p, base_dir, landscape, css))
    blocks = parse_blocks(html_text, base_dir)
    if not blocks:
        raise ConversionError("Il documento sembra vuoto.")
    if t == "docx":
        dest = ctx.out_file("docx")
        with atomic(dest) as tmp:
            blocks_to_docx(blocks, tmp)
        return [dest]
    if t == "md":
        content = blocks_to_md(blocks)
    elif t == "txt":
        content = blocks_to_txt(blocks)
    elif t == "html":
        content = html_text if ctx.key == "html" else wrap_html(html_text, ctx.stem)
    else:
        raise ConversionError("Conversione non supportata.")
    dest = ctx.out_file(t)
    with atomic(dest) as tmp:
        write_text(tmp, content)
    return [dest]


def sheets_to_pdf(ctx: Ctx, sheets) -> list:
    import sheets as sh
    ncols = sh.sheets_width(sheets)
    landscape = ncols > 6
    pt = 9.5 if ncols <= 8 else 8 if ncols <= 14 else 6.5
    css = BASE_CSS + f"\ntd, th {{ font-size: {pt}pt; padding: 2pt 4pt; }}\n"
    body = sh.sheets_to_html(sheets, ctx.stem, standalone=False)
    return emit_from_html(ctx, body, landscape=landscape, css=css)


def convert_document(ctx: Ctx) -> list:
    if ctx.key == "pdf":
        if ctx.target == "docx":
            return pdf_to_docx(ctx)
        if ctx.target in ("txt", "md", "html"):
            return pdf_to_text(ctx)
        return images.pdf_pages_to_images(ctx, ctx.source)
    body, base = source_to_html(ctx)
    return emit_from_html(ctx, body, base)

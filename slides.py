"""PPTX → PDF / immagini / testo, senza PowerPoint né LibreOffice.

Le diapositive vengono ridisegnate con PyMuPDF a partire dalla struttura del file:
testi (selezionabili), immagini, forme semplici, tabelle e colori del tema.
Non sono riprodotti: grafici, SmartArt, animazioni, sfumature complesse, font non standard.
"""
from __future__ import annotations

import html as htmllib
import io
import os
import re
import shutil
import tempfile

import docs
import images
from common import ConversionError, Ctx, atomic, fitz_mod

EMU_PT = 12700.0
_SERIF = ("times", "georgia", "cambria", "garamond", "palatino", "book antiqua", "serif")
_MONO = ("courier", "consolas", "mono", "menlo", "lucida console")


def _open(path):
    try:
        from pptx import Presentation
        return Presentation(path)
    except ImportError as exc:
        raise ConversionError("Manca il modulo python-pptx (pip install python-pptx).") from exc
    except Exception as exc:
        raise ConversionError("File PowerPoint non valido, danneggiato o protetto da password.") from exc


# ── colori ────────────────────────────────────────────────
def _theme_map(prs):
    names = ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4",
             "accent5", "accent6", "hlink", "folHlink"]
    out = {}
    try:
        from lxml import etree
        from pptx.opc.constants import RELATIONSHIP_TYPE as RT
        part = prs.slide_master.part.part_related_by(RT.THEME)
        root = etree.fromstring(part.blob)
        ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        for n in names:
            el = root.find(f".//a:clrScheme/a:{n}", ns)
            if el is None or not len(el):
                continue
            c = el[0]
            val = c.get("val") if c.tag.endswith("srgbClr") else c.get("lastClr")
            if val:
                out[n] = val
    except Exception:
        pass
    return out


_SCHEME = {"BACKGROUND_1": "lt1", "TEXT_1": "dk1", "BACKGROUND_2": "lt2", "TEXT_2": "dk2",
           "DARK_1": "dk1", "LIGHT_1": "lt1", "DARK_2": "dk2", "LIGHT_2": "lt2",
           "ACCENT_1": "accent1", "ACCENT_2": "accent2", "ACCENT_3": "accent3",
           "ACCENT_4": "accent4", "ACCENT_5": "accent5", "ACCENT_6": "accent6",
           "HYPERLINK": "hlink", "FOLLOWED_HYPERLINK": "folHlink"}


def _hex_to_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _color(cf, theme):
    """ColorFormat → (r,g,b) 0-255 oppure None."""
    try:
        if cf is None or cf.type is None:
            return None
        rgb = None
        try:
            rgb = _hex_to_rgb(str(cf.rgb))
        except Exception:
            tc = cf.theme_color
            key = _SCHEME.get(getattr(tc, "name", str(tc)).split(" ")[0].upper())
            if key and key in theme:
                rgb = _hex_to_rgb(theme[key])
        if rgb is None:
            return None
        br = getattr(cf, "brightness", 0) or 0
        if br > 0:
            rgb = tuple(int(c + (255 - c) * br) for c in rgb)
        elif br < 0:
            rgb = tuple(int(c * (1 + br)) for c in rgb)
        return rgb
    except Exception:
        return None


def _fill_rgb(shape, theme):
    try:
        from pptx.enum.dml import MSO_FILL
        f = shape.fill
        if f.type == MSO_FILL.SOLID:
            return _color(f.fore_color, theme)
        if f.type == MSO_FILL.GRADIENT:
            return _color(f.gradient_stops[0].color, theme)
    except Exception:
        pass
    return None


def _norm(rgb):
    return tuple(c / 255.0 for c in rgb) if rgb else None


def _lum(rgb):
    return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255.0


def _css_font(name):
    n = (name or "").lower()
    if any(s in n for s in _MONO):
        return "monospace"
    if any(s in n for s in _SERIF):
        return "serif"
    return "sans-serif"


# ── testo di una forma → HTML ──────────────────────────────
def _frame_html(tf, theme, default_pt, default_rgb, is_title=False, bullets_default=False, align_default="left"):
    from pptx.enum.text import PP_ALIGN
    ns_a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    parts = []
    for p in tf.paragraphs:
        spans = []
        for child in p._p:
            tag = child.tag.replace(ns_a, "")
            if tag == "br":
                spans.append("<br>")
                continue
            if tag not in ("r", "fld"):
                continue
            t = child.find(f"{ns_a}t")
            text = t.text if t is not None and t.text else ""
            if not text:
                continue
            from pptx.text.text import _Run
            run = _Run(child, p) if tag == "r" else None
            size = default_pt
            style = []
            if run is not None:
                f = run.font
                if f.size:
                    size = f.size.pt
                elif p.font.size:
                    size = p.font.size.pt
                rgb = _color(f.color, theme) if f.color and f.color.type is not None else None
                style.append(f"color:rgb({','.join(str(c) for c in (rgb or default_rgb))})")
                style.append(f"font-family:{_css_font(f.name)}")
                if f.bold or (is_title and f.bold is None):
                    style.append("font-weight:bold")
                if f.italic:
                    style.append("font-style:italic")
                if f.underline:
                    style.append("text-decoration:underline")
            else:
                style.append(f"color:rgb({','.join(str(c) for c in default_rgb)})")
            style.append(f"font-size:{size:g}pt")
            spans.append(f'<span style="{";".join(style)}">{htmllib.escape(text)}</span>')
        content = "".join(spans)
        if not content.strip():
            parts.append(f'<p style="margin:0;font-size:{default_pt * 0.6:g}pt">&nbsp;</p>')
            continue
        ppr = p._p.pPr
        has_bu = ppr is not None and (ppr.find(f"{ns_a}buChar") is not None or ppr.find(f"{ns_a}buAutoNum") is not None)
        no_bu = ppr is not None and ppr.find(f"{ns_a}buNone") is not None
        bullet = has_bu or (bullets_default and not no_bu)
        lvl = p.level or 0
        al = {PP_ALIGN.CENTER: "center", PP_ALIGN.RIGHT: "right", PP_ALIGN.JUSTIFY: "justify",
              PP_ALIGN.LEFT: "left"}.get(p.alignment, align_default)
        ml = lvl * 22 + (16 if bullet else 0)
        prefix = f'<span style="font-size:{default_pt:g}pt">•&nbsp;</span>' if bullet else ""
        parts.append(f'<p style="margin:0 0 {default_pt * 0.3:g}pt {ml}pt;text-align:{al}">{prefix}{content}</p>')
    return "".join(parts)


class _Renderer:
    def __init__(self, prs):
        self.fz = fitz_mod()
        self.prs = prs
        self.theme = _theme_map(prs)
        self.W = prs.slide_width / EMU_PT
        self.H = prs.slide_height / EMU_PT
        self.scratch = self.fz.open()
        self.scratch.new_page(width=self.W, height=self.H)

    def htmlbox(self, page, rect, html, anchor="top"):
        fz = self.fz
        if rect.width < 2 or rect.height < 2:
            return
        css = "body{margin:0;padding:0} p{line-height:1.15}"
        try:
            if anchor != "top":
                self.scratch.delete_page(0)
                sp = self.scratch.new_page(width=self.W, height=self.H)
                spare, _scale = sp.insert_htmlbox(rect, html, css=css, scale_low=0.35)
                if spare and spare > 0:
                    f = 0.5 if anchor == "middle" else 1.0
                    rect = fz.Rect(rect.x0, rect.y0 + spare * f, rect.x1, rect.y1 + 3)
            page.insert_htmlbox(rect, html, css=css, scale_low=0.35)
        except Exception:
            pass

    def draw_picture(self, page, shp, rect):
        blob = shp.image.blob
        crop = [getattr(shp, a, 0) or 0 for a in ("crop_left", "crop_top", "crop_right", "crop_bottom")]
        try:
            if any(crop):
                from PIL import Image
                with Image.open(io.BytesIO(blob)) as im:
                    w, h = im.size
                    box = (int(crop[0] * w), int(crop[1] * h), int(w - crop[2] * w), int(h - crop[3] * h))
                    buf = io.BytesIO()
                    im.convert("RGBA").crop(box).save(buf, "PNG")
                    blob = buf.getvalue()
            page.insert_image(rect, stream=blob)
        except Exception:
            try:  # formati che PyMuPDF non digerisce → prova con Pillow
                from PIL import Image
                with Image.open(io.BytesIO(shp.image.blob)) as im:
                    buf = io.BytesIO()
                    im.convert("RGBA").save(buf, "PNG")
                page.insert_image(rect, stream=buf.getvalue())
            except Exception:
                pass

    def draw_shape(self, page, shp, dark, depth=0):
        from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
        fz = self.fz
        try:
            st = shp.shape_type
        except Exception:
            st = None
        if st == MSO_SHAPE_TYPE.GROUP and depth < 6:
            for s in shp.shapes:
                self.draw_shape(page, s, dark, depth + 1)
            return
        if shp.left is None or shp.top is None or shp.width is None or shp.height is None:
            return
        l, t = shp.left / EMU_PT, shp.top / EMU_PT
        rect = fz.Rect(l, t, l + shp.width / EMU_PT, t + shp.height / EMU_PT)

        if st == MSO_SHAPE_TYPE.PICTURE or hasattr(shp, "image") and st != MSO_SHAPE_TYPE.PLACEHOLDER:
            try:
                self.draw_picture(page, shp, rect)
            except Exception:
                pass
            return
        if getattr(shp, "has_chart", False) and shp.has_chart:
            page.draw_rect(rect, color=(0.7, 0.7, 0.7), fill=(0.95, 0.95, 0.95), width=0.8)
            self.htmlbox(page, rect, '<p style="text-align:center;color:#777;font-size:12pt">[grafico non convertito]</p>', "middle")
            return
        if getattr(shp, "has_table", False) and shp.has_table:
            self.draw_table(page, shp, rect, dark)
            return

        text = ""
        if getattr(shp, "has_text_frame", False) and shp.has_text_frame:
            text = shp.text_frame.text.strip()
        fill = _fill_rgb(shp, self.theme) if hasattr(shp, "fill") else None
        line_rgb, line_w = None, 0.75
        try:
            from pptx.enum.dml import MSO_FILL
            if shp.line.fill.type == MSO_FILL.SOLID:
                line_rgb = _color(shp.line.fill.fore_color, self.theme)
                if shp.line.width:
                    line_w = max(0.25, shp.line.width / EMU_PT)
        except Exception:
            pass
        ast = None
        try:
            ast = str(shp.auto_shape_type).split(".")[-1].split(" ")[0].upper()
        except Exception:
            pass
        if st == MSO_SHAPE_TYPE.LINE or (st is None and ast is None and not text and line_rgb):
            try:
                page.draw_line(fz.Point(shp.begin_x / EMU_PT, shp.begin_y / EMU_PT),
                               fz.Point(shp.end_x / EMU_PT, shp.end_y / EMU_PT),
                               color=_norm(line_rgb or (90, 90, 90)), width=line_w)
            except Exception:
                pass
            return
        if (fill or line_rgb) and (ast in (None, "RECTANGLE", "ROUNDED_RECTANGLE", "OVAL", "ROUND_2_SAME_RECTANGLE",
                                            "SNIP_ROUND_RECTANGLE", "FLOWCHART_PROCESS") or text):
            kw = dict(color=_norm(line_rgb), fill=_norm(fill), width=line_w if line_rgb else 0)
            if ast == "OVAL":
                page.draw_oval(rect, **kw)
            elif ast and "ROUND" in ast:
                page.draw_rect(rect, radius=0.15, **kw)
            else:
                page.draw_rect(rect, **kw)
        if text:
            self.draw_text(page, shp, rect, fill, dark)

    def draw_text(self, page, shp, rect, fill, dark):
        from pptx.enum.shapes import PP_PLACEHOLDER
        from pptx.enum.text import MSO_ANCHOR
        tf = shp.text_frame
        ptype = None
        try:
            if shp.is_placeholder:
                ptype = shp.placeholder_format.type
        except Exception:
            pass
        is_title = ptype in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE, PP_PLACEHOLDER.VERTICAL_TITLE)
        is_sub = ptype == PP_PLACEHOLDER.SUBTITLE
        is_body = ptype in (PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT, PP_PLACEHOLDER.VERTICAL_BODY)
        size = 40 if ptype == PP_PLACEHOLDER.CENTER_TITLE else 32 if is_title else 24 if is_sub else 20 if is_body else 18
        bg_dark = _lum(fill) < 0.5 if fill else dark
        rgb = (255, 255, 255) if bg_dark else (20, 20, 20)
        align = "center" if ptype in (PP_PLACEHOLDER.CENTER_TITLE, PP_PLACEHOLDER.SUBTITLE) else "left"
        html = _frame_html(tf, self.theme, size, rgb, is_title, is_body, align)
        ml = (tf.margin_left if tf.margin_left is not None else 91440) / EMU_PT
        mr = (tf.margin_right if tf.margin_right is not None else 91440) / EMU_PT
        mt = (tf.margin_top if tf.margin_top is not None else 45720) / EMU_PT
        mb = (tf.margin_bottom if tf.margin_bottom is not None else 45720) / EMU_PT
        inner = self.fz.Rect(rect.x0 + ml, rect.y0 + mt, rect.x1 - mr, rect.y1 - mb)
        va = tf.vertical_anchor
        anchor = {MSO_ANCHOR.MIDDLE: "middle", MSO_ANCHOR.BOTTOM: "bottom"}.get(va, "middle" if (is_title and va is None) else "top")
        self.htmlbox(page, inner, html, anchor)

    def draw_table(self, page, shp, rect, dark):
        fz = self.fz
        tbl = shp.table
        cw = [c.width / EMU_PT for c in tbl.columns]
        rh = [r.height / EMU_PT for r in tbl.rows]
        y = rect.y0
        rgb_default = (255, 255, 255) if dark else (20, 20, 20)
        for ri, row in enumerate(tbl.rows):
            x = rect.x0
            for ci, cell in enumerate(row.cells):
                w = cw[ci] if ci < len(cw) else 60
                if getattr(cell, "is_spanned", False):
                    x += w
                    continue
                span_w = sum(cw[ci:ci + max(1, getattr(cell, "span_width", 1))]) if getattr(cell, "is_merge_origin", False) else w
                span_h = sum(rh[ri:ri + max(1, getattr(cell, "span_height", 1))]) if getattr(cell, "is_merge_origin", False) else rh[ri]
                r = fz.Rect(x, y, x + span_w, y + span_h)
                fill = _fill_rgb(cell, self.theme) if hasattr(cell, "fill") else None
                if fill is None and ri == 0:
                    fill = _color_first(self.theme)
                page.draw_rect(r, color=(0.72, 0.72, 0.72), fill=_norm(fill), width=0.6)
                crgb = (255, 255, 255) if (fill and _lum(fill) < 0.5) else (20, 20, 20) if fill else rgb_default
                html = _frame_html(cell.text_frame, self.theme, 12, crgb)
                self.htmlbox(page, fz.Rect(r.x0 + 4, r.y0 + 2, r.x1 - 4, r.y1 - 2), html, "middle")
                x += w
            y += rh[ri]

    def slide_bg(self, slide):
        try:
            from pptx.enum.dml import MSO_FILL
            f = slide.background.fill
            if f.type == MSO_FILL.SOLID:
                return _color(f.fore_color, self.theme)
        except Exception:
            pass
        try:  # sfondo del layout / master
            for src in (slide.slide_layout, slide.slide_layout.slide_master):
                f = src.background.fill
                from pptx.enum.dml import MSO_FILL
                if f.type == MSO_FILL.SOLID:
                    return _color(f.fore_color, self.theme)
        except Exception:
            pass
        return None

    def render(self, ctx=None):
        fz = self.fz
        doc = fz.open()
        for slide in self.prs.slides:
            if ctx:
                ctx.check()
            page = doc.new_page(width=self.W, height=self.H)
            bg = self.slide_bg(slide)
            if bg:
                page.draw_rect(page.rect, color=None, fill=_norm(bg))
            dark = bool(bg) and _lum(bg) < 0.45
            # decorazioni di layout e master (non i segnaposto)
            for src in (slide.slide_layout.slide_master, slide.slide_layout):
                try:
                    for s in src.shapes:
                        if not s.is_placeholder:
                            self.draw_shape(page, s, dark)
                except Exception:
                    pass
            for shp in slide.shapes:
                self.draw_shape(page, shp, dark)
        return doc


def _color_first(theme):
    h = theme.get("accent1")
    return _hex_to_rgb(h) if h else (68, 114, 196)


def pptx_to_pdf_file(src: str, dest: str, ctx=None):
    prs = _open(src)
    if not len(prs.slides):
        raise ConversionError("La presentazione non contiene diapositive.")
    doc = _Renderer(prs).render(ctx)
    try:
        doc.save(dest, garbage=3, deflate=True)
    finally:
        doc.close()


# ── testo ─────────────────────────────────────────────────
def pptx_to_html(src: str) -> str:
    prs = _open(src)
    out = []
    for i, slide in enumerate(prs.slides, 1):
        title = ""
        try:
            if slide.shapes.title is not None:
                title = slide.shapes.title.text_frame.text.strip()
        except Exception:
            pass
        out.append(f"<h2>Diapositiva {i}{': ' + htmllib.escape(title) if title else ''}</h2>")
        for shp in slide.shapes:
            try:
                if shp.is_placeholder and slide.shapes.title is not None and shp.shape_id == slide.shapes.title.shape_id:
                    continue
                if getattr(shp, "has_table", False) and shp.has_table:
                    rows = []
                    for row in shp.table.rows:
                        rows.append("<tr>" + "".join(f"<td>{htmllib.escape(c.text_frame.text)}</td>" for c in row.cells) + "</tr>")
                    out.append("<table>" + "".join(rows) + "</table>")
                elif getattr(shp, "has_text_frame", False) and shp.has_text_frame:
                    for p in shp.text_frame.paragraphs:
                        txt = "".join(r.text for r in p.runs).strip()
                        if txt:
                            out.append(f"<ul><li>{htmllib.escape(txt)}</li></ul>" if (p.level or 0) > 0 or shp.is_placeholder
                                       else f"<p>{htmllib.escape(txt)}</p>")
            except Exception:
                continue
        try:
            if slide.has_notes_slide:
                n = slide.notes_slide.notes_text_frame.text.strip()
                if n:
                    out.append(f"<blockquote>Note: {htmllib.escape(n)}</blockquote>")
        except Exception:
            pass
    return "\n".join(out)


def convert_slides(ctx: Ctx) -> list:
    t = ctx.target
    if t == "pdf":
        dest = ctx.out_file("pdf")
        with atomic(dest) as tmp:
            pptx_to_pdf_file(ctx.source, tmp, ctx)
        return [dest]
    if t in images.PIL_NAME:
        tmpd = tempfile.mkdtemp(prefix="cf-")
        try:
            pdf = os.path.join(tmpd, "s.pdf")
            pptx_to_pdf_file(ctx.source, pdf, ctx)
            return images.pdf_pages_to_images(ctx, pdf, dpi=150)
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)
    if t in ("txt", "md"):
        return docs.emit_from_html(ctx, pptx_to_html(ctx.source))
    raise ConversionError("Conversione non supportata.")

"""Fogli di calcolo e dati tabellari: XLSX, XLS (lettura), CSV, TSV, JSON."""
from __future__ import annotations

import csv
import datetime as dt
import html as htmllib
import io
import json
import re

from common import ConversionError, Ctx, atomic, read_text, write_text

Sheet = tuple  # (nome, righe) dove righe = list[list[valore]]


# ── Utilità valori ────────────────────────────────────────
def _fmt_value(v, comma_decimal=False) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            s = str(int(v))
        else:
            s = format(v, ".15g")
        return s.replace(".", ",") if comma_decimal else s
    if isinstance(v, dt.datetime):
        if v.time() == dt.time(0):
            return v.date().isoformat()
        return v.replace(microsecond=0).isoformat(sep=" ")
    if isinstance(v, (dt.date, dt.time)):
        return v.isoformat()
    return str(v)


def _json_value(v):
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return _fmt_value(v)
    return v


def _trim(rows):
    rows = [list(r) for r in rows]
    while rows and all(c in (None, "") for c in rows[-1]):
        rows.pop()
    width = 0
    for r in rows:
        for i in range(len(r) - 1, -1, -1):
            if r[i] not in (None, ""):
                width = max(width, i + 1)
                break
    return [r[:width] + [None] * (width - len(r[:width])) for r in rows]


def looks_like_header(rows) -> bool:
    if len(rows) < 2 or not rows[0]:
        return False
    first = rows[0]
    if not all(isinstance(c, str) and c.strip() for c in first):
        return False
    return len(set(first)) == len(first)


_INT = re.compile(r"^[+-]?(0|[1-9]\d{0,14})$")
_DEC_DOT = re.compile(r"^[+-]?(0|[1-9]\d*)\.\d+$")
_DEC_COMMA = re.compile(r"^[+-]?(0|[1-9]\d*),\d+$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DT = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$")


def coerce_cell(s, comma_decimal=False):
    """Trasforma in numero/data solo quando è inequivocabile (mai '007' o telefoni)."""
    if not isinstance(s, str):
        return s
    t = s.strip()
    if not t:
        return None
    if _INT.match(t):
        return int(t)
    if _DEC_DOT.match(t):
        return float(t)
    if comma_decimal and _DEC_COMMA.match(t):
        return float(t.replace(",", "."))
    try:
        if _ISO_DATE.match(t):
            return dt.datetime.strptime(t, "%Y-%m-%d")
        if _ISO_DT.match(t):
            return dt.datetime.fromisoformat(t.replace(" ", "T"))
    except ValueError:
        pass
    return s


# ── Lettura ───────────────────────────────────────────────
def _sniff(text: str) -> str:
    lines = [l for l in text.splitlines()[:40] if l.strip()]
    best, best_score = ",", 0.0
    for d in (",", ";", "\t", "|"):
        try:
            counts = [len(r) for r in csv.reader(lines, delimiter=d)]
        except csv.Error:
            continue
        if not counts:
            continue
        mode = max(set(counts), key=counts.count)
        if mode < 2:
            continue
        score = counts.count(mode) / len(counts) * 100 + min(mode, 50) * 0.01
        if score > best_score + 1e-9:
            best, best_score = d, score
    return best


def read_delimited(path: str, forced: str | None = None):
    text = read_text(path)
    delim = forced or _sniff(text)
    rows = [r for r in csv.reader(io.StringIO(text, newline=""), delimiter=delim)]
    return [("Foglio1", _trim(rows))], delim


def read_xlsx(path: str):
    from openpyxl import load_workbook
    try:
        wb = load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:
        raise ConversionError("File Excel non valido, danneggiato o protetto da password.") from exc
    sheets = []
    try:
        for ws in wb.worksheets:
            if getattr(ws, "sheet_state", "visible") != "visible":
                continue
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            sheets.append((ws.title, _trim(rows)))
    finally:
        wb.close()
    if not sheets:
        raise ConversionError("Il file Excel non contiene fogli visibili.")
    return sheets


def read_xls(path: str):
    try:
        import xlrd
    except ImportError as exc:
        raise ConversionError("Manca il modulo xlrd (pip install xlrd).") from exc
    try:
        book = xlrd.open_workbook(path)
    except Exception as exc:
        raise ConversionError("File .xls non valido, danneggiato o protetto da password.") from exc
    sheets = []
    for sh in book.sheets():
        if sh.visibility != 0:
            continue
        rows = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                t, v = cell.ctype, cell.value
                if t in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    row.append(None)
                elif t == xlrd.XL_CELL_DATE:
                    try:
                        row.append(xlrd.xldate_as_datetime(v, book.datemode))
                    except Exception:
                        row.append(v)
                elif t == xlrd.XL_CELL_BOOLEAN:
                    row.append(bool(v))
                elif t == xlrd.XL_CELL_ERROR:
                    row.append(None)
                else:
                    row.append(v)
            rows.append(row)
        sheets.append((sh.name, _trim(rows)))
    if not sheets:
        raise ConversionError("Il file non contiene fogli visibili.")
    return sheets


def read_json(path: str):
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise ConversionError(f"JSON non valido (riga {exc.lineno}): {exc.msg}.") from exc

    def table(obj, name):
        if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
            keys = []
            for d in obj:
                for k in d:
                    if k not in keys:
                        keys.append(k)
            rows = [keys] + [[_cell(d.get(k)) for k in keys] for d in obj]
            return (name, rows)
        if isinstance(obj, list) and all(isinstance(x, list) for x in obj) and obj:
            return (name, [[_cell(c) for c in r] for r in obj])
        if isinstance(obj, list) and obj and all(not isinstance(x, (dict, list)) for x in obj):
            return (name, [[name]] + [[x] for x in obj])
        return None

    def _cell(v):
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return v

    t = table(data, "Foglio1")
    if t:
        return [t]
    if isinstance(data, dict):
        sheets = [table(v, str(k)[:31]) for k, v in data.items()]
        if sheets and all(sheets):
            return sheets
        # oggetto semplice → due colonne chiave/valore
        return [("Foglio1", [["chiave", "valore"]] + [[k, _cell(v)] for k, v in data.items()])]
    raise ConversionError("Il JSON non ha una forma tabellare (serve un elenco di oggetti o di liste).")


def load_sheets(ctx: Ctx):
    """Ritorna (fogli, separatore_csv_rilevato)."""
    k = ctx.key
    if k == "xlsx":
        return read_xlsx(ctx.source), None
    if k == "xls":
        return read_xls(ctx.source), None
    if k == "csv":
        return read_delimited(ctx.source)
    if k == "tsv":
        return read_delimited(ctx.source, "\t")
    if k == "json":
        return read_json(ctx.source), None
    raise ConversionError("Formato di foglio non supportato.")


# ── Scrittura ─────────────────────────────────────────────
def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\[\]]+', "_", name).strip() or "Foglio"


def _write_delimited(ctx: Ctx, sheets, delim: str, ext: str) -> list:
    comma = delim == ";"
    out = []
    multi = len(sheets) > 1
    for name, rows in sheets:
        ctx.check()
        buf = io.StringIO(newline="")
        w = csv.writer(buf, delimiter=delim, lineterminator="\r\n")
        for r in rows:
            w.writerow([_fmt_value(v, comma) for v in r])
        dest = ctx.out_file(ext, f" - {_safe(name)}" if multi else "")
        with atomic(dest) as tmp:
            write_text(tmp, buf.getvalue(), bom=True)
        out.append(dest)
    return out


def _write_json(ctx: Ctx, sheets) -> list:
    def conv(rows):
        if looks_like_header(rows):
            keys = rows[0]
            return [{k: _json_value(v) for k, v in zip(keys, r)} for r in rows[1:]]
        return [[_json_value(v) for v in r] for r in rows]
    data = conv(sheets[0][1]) if len(sheets) == 1 else {n: conv(r) for n, r in sheets}
    dest = ctx.out_file("json")
    with atomic(dest) as tmp:
        write_text(tmp, json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return [dest]


def _write_xlsx(ctx: Ctx, sheets) -> list:
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    used = set()
    for name, rows in sheets:
        title = _safe(name)[:31]
        base, i = title, 1
        while title.lower() in used:
            i += 1
            title = f"{base[:28]}_{i}"
        used.add(title.lower())
        ws = wb.create_sheet(title)
        widths = {}
        for r in rows:
            r = [ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v for v in r]
            ws.append(r)
            for ci, v in enumerate(r, 1):
                widths[ci] = max(widths.get(ci, 0), len(_fmt_value(v)))
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, dt.datetime):
                    c.number_format = ("yyyy-mm-dd" if c.value.time() == dt.time(0)
                                       else "yyyy-mm-dd hh:mm:ss")
        for ci, wd in widths.items():
            ws.column_dimensions[get_column_letter(ci)].width = min(max(wd + 2, 8), 60)
        if looks_like_header(rows):
            for c in ws[1]:
                c.font = Font(bold=True)
            ws.freeze_panes = "A2"
    dest = ctx.out_file("xlsx")
    with atomic(dest) as tmp:
        wb.save(tmp)
    return [dest]


def sheets_to_html(sheets, title="Tabella", standalone=True) -> str:
    parts = []
    for name, rows in sheets:
        if len(sheets) > 1:
            parts.append(f"<h2>{htmllib.escape(name)}</h2>")
        header = looks_like_header(rows)
        parts.append("<table>")
        for ri, r in enumerate(rows):
            tag = "th" if (header and ri == 0) else "td"
            cells = "".join(
                f"<{tag}>{htmllib.escape(_fmt_value(v))}</{tag}>" for v in r)
            parts.append(f"<tr>{cells}</tr>")
        parts.append("</table>")
    body = "\n".join(parts)
    if not standalone:
        return body
    return ("<!doctype html>\n<html lang=\"it\"><head><meta charset=\"utf-8\">"
            f"<title>{htmllib.escape(title)}</title>\n<style>"
            "body{font-family:Segoe UI,Arial,sans-serif;margin:2em}"
            "table{border-collapse:collapse;margin-bottom:2em}"
            "td,th{border:1px solid #bbb;padding:4px 8px;text-align:left}"
            "th{background:#eef2f7}</style></head><body>\n" + body + "\n</body></html>\n")


def sheets_width(sheets) -> int:
    return max((len(r) for _, rows in sheets for r in rows), default=1)


def convert_sheet(ctx: Ctx, to_pdf) -> list:
    """to_pdf(ctx, html_fragment, landscape, font_pt) → percorso: fornita da docs.py."""
    sheets, detected = load_sheets(ctx)
    t = ctx.target
    # CSV ⇄ TSV: si preservano i testi esattamente, senza reinterpretare i valori
    if t == "csv":
        return _write_delimited(ctx, sheets, ctx.opts.csv_sep, "csv")
    if t == "tsv":
        return _write_delimited(ctx, sheets, "\t", "tsv")
    if ctx.key in ("csv", "tsv"):  # testi → valori tipizzati per JSON/XLSX
        comma = detected in (";", "\t", "|")
        sheets = [(n, [[coerce_cell(c, comma) for c in r] for r in rows]) for n, rows in sheets]
        if ctx.key in ("csv", "tsv"):
            sheets = [(ctx.stem[:31] or "Foglio1", sheets[0][1])]
    if t == "json":
        return _write_json(ctx, sheets)
    if t == "xlsx":
        return _write_xlsx(ctx, sheets)
    if t == "html":
        doc = sheets_to_html(sheets, ctx.stem)
        dest = ctx.out_file("html")
        with atomic(dest) as tmp:
            write_text(tmp, doc)
        return [dest]
    if t == "pdf":
        return to_pdf(ctx, sheets)
    raise ConversionError("Conversione non supportata.")

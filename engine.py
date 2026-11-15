"""API pubblica del motore di conversione di ConvertiFacile.

    targets_for(path)  → formati di destinazione disponibili
    default_target(path)
    convert(path, target, out_dir, options, cancel)  → lista dei file creati
"""
from __future__ import annotations

import os
import zipfile

from PIL import Image

import docs
import formats
import images
import sheets
import slides
from common import Cancelled, ConversionError, Ctx, Options, fitz_mod

__all__ = ["Options", "ConversionError", "Cancelled", "targets_for", "default_target",
           "convert", "can_read", "can_write", "supported_keys"]

_DOC_TARGETS = {
    "pdf": ["docx", "txt", "md", "html", "png", "jpg", "webp", "tiff"],
    "docx": ["pdf", "txt", "md", "html", "png", "jpg"],
    "pptx": ["pdf", "png", "jpg", "txt", "md"],
    "xlsx": ["csv", "tsv", "json", "html", "pdf"],
    "xls": ["xlsx", "csv", "tsv", "json", "html", "pdf"],
    "csv": ["xlsx", "tsv", "json", "html", "pdf"],
    "tsv": ["xlsx", "csv", "json", "html", "pdf"],
    "json": ["csv", "tsv", "xlsx", "html", "pdf"],
    "txt": ["pdf", "docx", "md", "html"],
    "md": ["pdf", "docx", "html", "txt"],
    "html": ["pdf", "docx", "md", "txt"],
}
_DEFAULT = {
    "png": "jpg", "jpg": "png", "webp": "png", "gif": "png", "bmp": "png", "tiff": "png",
    "heic": "jpg", "avif": "jpg", "jxl": "jpg", "jp2": "jpg", "svg": "png", "ico": "png",
    "pdf": "docx", "docx": "pdf", "pptx": "pdf", "xlsx": "pdf", "xls": "xlsx", "csv": "xlsx",
    "tsv": "xlsx", "json": "csv", "txt": "pdf", "md": "pdf", "html": "pdf",
}


def can_read(key: str) -> bool:
    kind = formats.kind_of(key)
    if kind == "image":
        return images.can_read(key)
    return key in _DOC_TARGETS


def can_write(key: str) -> bool:
    kind = formats.kind_of(key)
    if kind == "image":
        return images.can_write(key) or False
    return key in {t for ts in _DOC_TARGETS.values() for t in ts}


def supported_keys():
    return list(formats.FORMATS)


def targets_for(path: str) -> list:
    key = formats.key_for_path(path)
    if key is None:
        return []
    if formats.kind_of(key) == "image":
        if not images.can_read(key):
            return []
        out = [k for k in images.write_keys() if k != key and not (key == "cur" and k == "ico")]
        return out + ["pdf"]
    out = []
    for t in _DOC_TARGETS.get(key, []):
        if t in images.PIL_NAME and not images.can_write(t):
            continue
        out.append(t)
    return out


def default_target(path: str):
    key = formats.key_for_path(path)
    ts = targets_for(path)
    pref = _DEFAULT.get(key, "png")
    if pref in ts:
        return pref
    return ts[0] if ts else None


def _friendly(exc: Exception) -> str:
    if isinstance(exc, PermissionError):
        return "Permesso negato: il file è aperto in un altro programma o la cartella è protetta."
    if isinstance(exc, FileNotFoundError):
        return "File o cartella non trovati."
    if isinstance(exc, zipfile.BadZipFile):
        return "Il file è danneggiato o non è del tipo indicato dall'estensione."
    if isinstance(exc, Image.DecompressionBombError):
        return "Immagine troppo grande (protezione contro i file malevoli)."
    if isinstance(exc, MemoryError):
        return "Memoria insufficiente per questo file."
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return "Spazio su disco esaurito."
    return f"{type(exc).__name__}: {exc}"


def convert(source: str, target: str, out_dir: str, opts: Options | None = None, cancel=None) -> list:
    """Converte `source` in `target`; ritorna i percorsi creati. Solleva ConversionError."""
    opts = opts or Options()
    key = formats.key_for_path(source)
    if key is None:
        raise ConversionError("Formato non riconosciuto.")
    if not os.path.isfile(source):
        raise ConversionError("File non trovato.")
    if target not in targets_for(source):
        raise ConversionError(f"Da {formats.label(key)} a {formats.label(target)} non è supportato.")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as exc:
        raise ConversionError(f"Cartella di destinazione non utilizzabile ({exc.strerror or exc}).") from exc
    ctx = Ctx(source, key, target, out_dir, opts, cancel)
    kind = formats.kind_of(key)
    try:
        ctx.check()
        if kind == "image":
            return images.image_to_pdf(ctx) if target == "pdf" else images.image_to_image(ctx)
        if kind == "slides":
            return slides.convert_slides(ctx)
        if kind == "sheet":
            return sheets.convert_sheet(ctx, docs.sheets_to_pdf)
        return docs.convert_document(ctx)
    except (ConversionError, Cancelled):
        raise
    except Exception as exc:  # errore imprevisto: messaggio leggibile, dettagli nel testo
        raise ConversionError(_friendly(exc)) from exc

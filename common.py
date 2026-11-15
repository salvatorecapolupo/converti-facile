"""Tipi e utilità condivise dai moduli di conversione."""
from __future__ import annotations

import codecs
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field


class ConversionError(Exception):
    """Errore comprensibile da mostrare all'utente."""


class Cancelled(Exception):
    """Conversione annullata dall'utente."""


@dataclass
class Options:
    quality: int = 90            # 1-100: JPEG, WebP, AVIF, HEIC, JPEG XL, JPEG 2000
    strip_metadata: bool = False  # rimuove EXIF/GPS dalle immagini
    overwrite: bool = False       # False = non sovrascrive mai, aggiunge " (1)"
    csv_sep: str = ";"            # separatore CSV in uscita


@dataclass
class Ctx:
    source: str
    key: str                      # formato di partenza
    target: str                   # formato di arrivo
    out_dir: str
    opts: Options
    cancel: object = None         # threading.Event (opzionale)
    stem: str = field(init=False)

    def __post_init__(self):
        self.stem = os.path.splitext(os.path.basename(self.source))[0]

    def check(self):
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled()

    # ── percorsi di output ──
    def _free(self, make):
        p = make("")
        if self.opts.overwrite and os.path.abspath(p) != os.path.abspath(self.source):
            return p
        i = 0
        while os.path.exists(p) or os.path.abspath(p) == os.path.abspath(self.source):
            i += 1
            p = make(f" ({i})")
        return p

    def out_file(self, ext: str, suffix: str = "") -> str:
        return self._free(lambda n: os.path.join(self.out_dir, f"{self.stem}{suffix}{n}.{ext}"))

    def out_folder(self, suffix: str) -> str:
        return self._free(lambda n: os.path.join(self.out_dir, f"{self.stem}{suffix}{n}"))


@contextmanager
def atomic(dest: str):
    """Scrive su un file temporaneo (stessa estensione) e lo rinomina solo a fine lavoro."""
    d, base = os.path.split(dest)
    tmp = os.path.join(d, f".~cf-{uuid.uuid4().hex[:8]}-{base}")
    try:
        yield tmp
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def fitz_mod():
    """PyMuPDF (il pacchetto si chiama `pymupdf`, il vecchio alias `fitz`)."""
    try:
        import pymupdf as fz
    except ImportError:
        try:
            import fitz as fz
        except ImportError as exc:
            raise ConversionError("Manca il modulo PyMuPDF (pip install PyMuPDF).") from exc
    return fz


def read_text(path: str) -> str:
    """Legge un file di testo indovinando la codifica (BOM, UTF-8, poi Windows-1252)."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(codecs.BOM_UTF8):
        return raw[3:].decode("utf-8", errors="replace")
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1252")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def write_text(path: str, text: str, bom: bool = False):
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        f.write(text)

"""Conversioni di immagini (Pillow + plugin opzionali + PyMuPDF per SVG e PDF)."""
from __future__ import annotations

import os

from PIL import Image, ImageOps, ImageSequence

from common import ConversionError, Ctx, atomic, fitz_mod
import formats

# ── Plugin opzionali: se mancano, il formato semplicemente non compare ──
def _register_plugins():
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
    for mod in ("pillow_avif", "pillow_jxl"):
        try:
            __import__(mod)
        except Exception:
            pass


_register_plugins()
Image.init()

PIL_NAME = {  # chiave → nome formato Pillow
    "png": "PNG", "jpg": "JPEG", "gif": "GIF", "webp": "WEBP", "bmp": "BMP",
    "tiff": "TIFF", "ico": "ICO", "icns": "ICNS", "avif": "AVIF", "heic": "HEIF",
    "jp2": "JPEG2000", "jxl": "JXL", "tga": "TGA", "pcx": "PCX", "ppm": "PPM",
    "qoi": "QOI", "xbm": "XBM", "cur": "CUR", "sgi": "SGI", "dds": "DDS",
    "psd": "PSD", "xpm": "XPM",
}
WRITE_ORDER = ["png", "jpg", "webp", "gif", "bmp", "tiff", "ico", "avif", "heic",
               "jp2", "jxl", "icns", "tga", "pcx", "ppm", "xbm", "qoi"]

# modi colore accettati da ciascun formato in scrittura
MODES = {
    "jpg": {"L", "RGB", "CMYK"},
    "png": {"1", "L", "LA", "I;16", "P", "RGB", "RGBA"},
    "gif": {"P", "L"},
    "webp": {"RGB", "RGBA"},
    "bmp": {"1", "L", "P", "RGB"},
    "tiff": {"1", "L", "LA", "P", "RGB", "RGBA", "CMYK", "I;16"},
    "ico": {"RGBA"}, "icns": {"RGBA"},
    "avif": {"RGB", "RGBA"}, "heic": {"RGB", "RGBA"}, "jxl": {"RGB", "RGBA", "L", "LA"},
    "jp2": {"L", "LA", "RGB", "RGBA"},
    "tga": {"1", "L", "LA", "P", "RGB", "RGBA"},
    "pcx": {"1", "L", "P", "RGB"},
    "ppm": {"1", "L", "RGB"},
    "qoi": {"RGB", "RGBA"},
    "xbm": {"1"},
}
ALPHA_OK = {"png", "webp", "tiff", "ico", "icns", "avif", "heic", "jxl", "jp2", "tga", "gif", "qoi"}
ANIMATED_OUT = {"gif", "webp"}


def can_read(key: str) -> bool:
    if key == "svg":
        try:
            fitz_mod()
            return True
        except ConversionError:
            return False
    return PIL_NAME.get(key) in Image.OPEN


def can_write(key: str) -> bool:
    return key in PIL_NAME and PIL_NAME[key] in Image.SAVE


def write_keys():
    return [k for k in WRITE_ORDER if can_write(k)]


# ── Lettura ───────────────────────────────────────────────
def render_svg(path: str) -> Image.Image:
    fz = fitz_mod()
    try:
        doc = fz.open(path, filetype="svg")
        page = doc[0]
        r = page.rect
        zoom = max(1.0, 1024.0 / max(r.width, r.height, 1))
        pix = page.get_pixmap(matrix=fz.Matrix(zoom, zoom), alpha=True)
        img = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
        doc.close()
        return img
    except Exception as exc:
        raise ConversionError(f"SVG non leggibile ({exc}).") from exc


def open_image(path: str, key: str) -> Image.Image:
    if key == "svg":
        return render_svg(path)
    return Image.open(path)


# ── Preparazione pixel ────────────────────────────────────
def _has_alpha(im: Image.Image) -> bool:
    if im.mode in ("RGBA", "LA", "PA", "RGBa", "La"):
        return True
    return "transparency" in im.info


def _flatten(im: Image.Image, bg=(255, 255, 255)) -> Image.Image:
    rgba = im.convert("RGBA")
    base = Image.new("RGBA", rgba.size, bg + (255,))
    base.alpha_composite(rgba)
    return base.convert("RGB")


def _cmyk_to_rgb(im: Image.Image) -> Image.Image:
    icc = im.info.get("icc_profile")
    if icc:
        try:
            import io
            from PIL import ImageCms
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            out = ImageCms.profileToProfile(im, src, dst, outputMode="RGB")
            out.info.pop("icc_profile", None)
            return out
        except Exception:
            pass
    return im.convert("RGB")


def _to_8bit(im: Image.Image) -> Image.Image:
    if im.mode.startswith("I;16"):
        return im.point(lambda v: v * (1 / 256)).convert("L")
    if im.mode == "I":
        return im.point(lambda v: v * (1 / 256)).convert("L")
    return im.convert("L")  # "F"


def coerce(im: Image.Image, key: str) -> Image.Image:
    """Porta l'immagine in un modo colore che il formato di arrivo sa scrivere."""
    allowed = MODES[key]
    if key == "xbm":
        return (_flatten(im) if _has_alpha(im) else im).convert("1")
    if _has_alpha(im) and key not in ALPHA_OK:
        im = _flatten(im)
    for _ in range(4):
        mode = im.mode
        if mode in allowed:
            return im
        has_a = _has_alpha(im)
        if mode == "CMYK":
            im = _cmyk_to_rgb(im)
        elif mode.startswith("I") or mode == "F":
            im = _to_8bit(im)
        elif mode in ("P", "PA"):
            im = im.convert("RGBA" if has_a and "RGBA" in allowed else "RGB")
        elif mode in ("LA", "La"):
            im = im.convert("RGBA" if "RGBA" in allowed else "L")
        elif mode in ("RGBA", "RGBa"):
            im = im.convert("RGBA") if "RGBA" in allowed else _flatten(im)
        elif mode in ("1", "L"):
            im = im.convert("RGBA" if "RGBA" in allowed and key in ("ico", "icns", "qoi") else "RGB")
        else:  # YCbCr, LAB, HSV, ...
            im = im.convert("RGB")
    return im.convert("RGB")


def _pad_square(im: Image.Image) -> Image.Image:
    w, h = im.size
    if w == h:
        return im
    s = max(w, h)
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    canvas.paste(im.convert("RGBA"), ((s - w) // 2, (s - h) // 2))
    return canvas


def _save_kwargs(key: str, im: Image.Image, q: int, icc, exif):
    kw = {}
    if key == "jpg":
        kw.update(quality=q, optimize=True)
        if q >= 90:
            kw["subsampling"] = 0
    elif key == "png":
        kw.update(optimize=True)
    elif key == "webp":
        kw.update(quality=q, method=4)
        if q >= 100:
            kw["lossless"] = True
    elif key == "tiff":
        kw.update(compression="group4" if im.mode == "1" else "tiff_lzw")
    elif key == "avif":
        kw.update(quality=q, speed=6)
    elif key == "heic":
        kw.update(quality=q)
    elif key == "jxl":
        kw.update(quality=q) if q < 100 else kw.update(lossless=True)
    elif key == "jp2":
        if q < 100:
            kw.update(irreversible=True, quality_mode="rates",
                      quality_layers=[max(1.0, (101 - q) / 4.0)])
    elif key == "ico":
        side = im.size[0]
        sizes = [s for s in (16, 24, 32, 48, 64, 128, 256) if s <= side] or [side]
        kw.update(sizes=[(s, s) for s in sizes])
    if icc and key in ("jpg", "png", "webp", "tiff"):
        kw["icc_profile"] = icc
    if exif and key in ("jpg", "png", "webp"):
        kw["exif"] = exif
    return kw


def _meta(src: Image.Image, strip: bool):
    if strip:
        return None, None
    icc = src.info.get("icc_profile")
    exif = None
    try:
        ex = src.getexif()
        if ex:
            exif = ex.tobytes()
    except Exception:
        pass
    return icc, exif


def _save(im: Image.Image, dest: str, key: str, q: int, icc, exif, **extra):
    kw = _save_kwargs(key, im, q, icc, exif)
    kw.update(extra)
    with atomic(dest) as tmp:
        try:
            im.save(tmp, format=PIL_NAME[key], **kw)
        except Exception:
            # ritenta senza metadati (alcuni EXIF non sono scrivibili)
            kw.pop("exif", None)
            kw.pop("icc_profile", None)
            im.save(tmp, format=PIL_NAME[key], **kw)


# ── Immagine → immagine ───────────────────────────────────
def image_to_image(ctx: Ctx) -> list:
    key, target, q = ctx.key, ctx.target, ctx.opts.quality
    if not can_read(key):
        raise ConversionError(f"Questo computer non può leggere il formato {formats.label(key)}.")
    if not can_write(target):
        raise ConversionError(f"Questo computer non può scrivere il formato {formats.label(target)}.")
    try:
        src = open_image(ctx.source, key)
    except Image.DecompressionBombError as exc:
        raise ConversionError("Immagine troppo grande (protezione contro i file malevoli).") from exc
    except Exception as exc:
        if isinstance(exc, ConversionError):
            raise
        raise ConversionError("File non riconosciuto o danneggiato.") from exc

    with src:
        n = getattr(src, "n_frames", 1)
        animated = bool(getattr(src, "is_animated", False)) and src.format in ("GIF", "WEBP", "PNG", "AVIF", "MPO") \
            and src.format != "MPO"
        multipage = n > 1 and src.format == "TIFF"

        # animazioni conservate verso GIF / WebP
        if animated and target in ANIMATED_OUT:
            return _save_animation(ctx, src, target)

        # TIFF multipagina verso altro formato → una cartella con una immagine per pagina
        if multipage and target != "tiff":
            folder = ctx.out_folder("_pagine")
            os.makedirs(folder, exist_ok=True)
            out = []
            for i, frame in enumerate(ImageSequence.Iterator(src), 1):
                ctx.check()
                icc, exif = _meta(frame, ctx.opts.strip_metadata)
                im = coerce(frame.copy(), target)
                if target == "ico":
                    im = _pad_square(im)
                dest = os.path.join(folder, f"{ctx.stem}_p{i:03d}.{target}")
                _save(im, dest, target, q, icc, exif)
                out.append(dest)
            return out

        if multipage and target == "tiff":
            frames = [coerce(f.copy(), "tiff") for f in ImageSequence.Iterator(src)]
            dest = ctx.out_file("tiff")
            with atomic(dest) as tmp:
                frames[0].save(tmp, format="TIFF", save_all=True, append_images=frames[1:],
                               compression="tiff_lzw")
            return [dest]

        # caso normale: un'immagine (per le animazioni verso formati statici, il primo fotogramma)
        base = src
        if key != "svg" and not animated:
            base = ImageOps.exif_transpose(src)
        icc, exif = _meta(base, ctx.opts.strip_metadata)
        im = coerce(base.copy() if base is src else base, target)
        if target in ("ico", "icns"):
            im = _pad_square(im)
            if target == "icns" and im.size[0] < 16:
                im = im.resize((16, 16), Image.LANCZOS)
        dest = ctx.out_file(target)
        _save(im, dest, target, q, icc, exif)
        return [dest]


def _save_animation(ctx: Ctx, src: Image.Image, target: str) -> list:
    frames, durations = [], []
    for fr in ImageSequence.Iterator(src):
        ctx.check()
        frames.append(fr.convert("RGBA"))
        durations.append(fr.info.get("duration", src.info.get("duration", 100)) or 100)
    loop = src.info.get("loop", 0)
    dest = ctx.out_file(target)
    kw = dict(save_all=True, append_images=frames[1:], duration=durations, loop=loop)
    with atomic(dest) as tmp:
        if target == "gif":
            frames[0].save(tmp, format="GIF", disposal=2, **kw)
        else:
            frames[0].save(tmp, format="WEBP", quality=ctx.opts.quality, method=4, **kw)
    return [dest]


# ── Immagine → PDF ────────────────────────────────────────
def image_to_pdf(ctx: Ctx) -> list:
    try:
        src = open_image(ctx.source, ctx.key)
    except Exception as exc:
        raise ConversionError("File non riconosciuto o danneggiato.") from exc
    with src:
        dpi = 150
        try:
            d = src.info.get("dpi")
            if d and d[0] and 50 <= float(d[0]) <= 1200:
                dpi = float(d[0])
        except Exception:
            pass
        n = getattr(src, "n_frames", 1)
        pages = []
        for fr in (ImageSequence.Iterator(src) if (n > 1 and src.format == "TIFF") else [src]):
            ctx.check()
            im = fr.copy() if fr is not src else ImageOps.exif_transpose(src)
            im = _flatten(im) if _has_alpha(im) else im
            if im.mode not in ("L", "RGB", "1", "CMYK"):
                im = coerce(im, "jpg") if im.mode != "I;16" else _to_8bit(im)
            pages.append(im)
        dest = ctx.out_file("pdf")
        with atomic(dest) as tmp:
            kw = {} if pages[0].mode == "1" else {"quality": max(60, ctx.opts.quality)}
            pages[0].save(tmp, format="PDF", resolution=dpi, save_all=True,
                          append_images=pages[1:], **kw)
    return [dest]


# ── Pagine PDF → immagini ─────────────────────────────────
def pdf_pages_to_images(ctx: Ctx, pdf_path: str, dpi: int = 200) -> list:
    fz = fitz_mod()
    target = ctx.target
    if not can_write(target):
        raise ConversionError(f"Questo computer non può scrivere il formato {formats.label(target)}.")
    doc = fz.open(pdf_path)
    try:
        if doc.needs_pass:
            raise ConversionError("Il PDF è protetto da password.")
        n = len(doc)
        if n == 0:
            raise ConversionError("Il PDF non contiene pagine.")
        folder = None
        if n > 1:
            folder = ctx.out_folder("_pagine")
            os.makedirs(folder, exist_ok=True)
        out = []
        for i in range(n):
            ctx.check()
            pix = doc[i].get_pixmap(dpi=dpi, alpha=False)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            im = coerce(im, target)
            if folder:
                dest = os.path.join(folder, f"{ctx.stem}_p{i + 1:03d}.{target}")
            else:
                dest = ctx.out_file(target)
            _save(im, dest, target, ctx.opts.quality, None, None)
            out.append(dest)
        return out
    finally:
        doc.close()

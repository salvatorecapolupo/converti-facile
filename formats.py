"""Catalogo dei formati di ConvertiFacile.

Per ogni formato: nome, famiglia, estensioni e UNA frase che spiega di cosa si
tratta e racconta un pezzo della sua storia (mostrata nell'interfaccia).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Fmt:
    key: str          # chiave canonica, anche estensione di output (es. "jpg")
    label: str        # nome mostrato (es. "JPEG")
    kind: str         # image | document | slides | sheet | text
    exts: tuple       # estensioni riconosciute in ingresso
    blurb: str        # cos'è + storia, una frase


KINDS = {
    "image": "Immagini",
    "document": "Documenti",
    "slides": "Presentazioni",
    "sheet": "Fogli di calcolo e dati",
    "text": "Testo e web",
}

_LIST = [
    # ── Immagini ──────────────────────────────────────────────
    Fmt("png", "PNG", "image", (".png", ".apng"),
        "Portable Network Graphics: nato nel 1995 come alternativa libera al GIF (allora coperto da brevetto), "
        "comprime senza perdita, gestisce la trasparenza ed è raccomandazione W3C dal 1996."),
    Fmt("jpg", "JPEG", "image", (".jpg", ".jpeg", ".jpe", ".jfif"),
        "JPEG: standard del 1992 del Joint Photographic Experts Group, comprime le fotografie con una perdita "
        "di qualità regolabile ed è ancora oggi il formato fotografico più diffuso."),
    Fmt("gif", "GIF", "image", (".gif",),
        "GIF (Graphics Interchange Format): creato da CompuServe nel 1987 e limitato a 256 colori; dal 1989 "
        "supporta le animazioni, che ne hanno garantito la sopravvivenza sul web."),
    Fmt("webp", "WebP", "image", (".webp",),
        "WebP: presentato da Google nel 2010 e basato sul codec video VP8, comprime con o senza perdita e "
        "supporta trasparenza e animazione; oggi funziona in tutti i browser."),
    Fmt("bmp", "BMP", "image", (".bmp", ".dib"),
        "BMP: la bitmap di Windows e OS/2, nata alla fine degli anni Ottanta; conserva i pixel quasi senza "
        "compressione, quindi è semplicissimo ma molto pesante."),
    Fmt("tiff", "TIFF", "image", (".tif", ".tiff"),
        "TIFF: creato da Aldus nel 1986 per scansioni e stampa professionale (oggi sotto Adobe); gestisce più "
        "pagine, molti livelli di colore e compressione senza perdita."),
    Fmt("ico", "ICO", "image", (".ico",),
        "ICO: il formato delle icone di Windows; un solo file contiene la stessa icona in più dimensioni ed è "
        "usato anche per la favicon dei siti, introdotta da Internet Explorer 5 nel 1999."),
    Fmt("cur", "CUR", "image", (".cur",),
        "CUR: il formato dei cursori del mouse di Windows, identico all'ICO ma con in più il punto attivo "
        "(hotspot) del puntatore."),
    Fmt("icns", "ICNS", "image", (".icns",),
        "ICNS: formato delle icone di macOS, introdotto con Mac OS X nel 2001; contiene la stessa icona a più "
        "risoluzioni, fino a quelle per gli schermi Retina."),
    Fmt("avif", "AVIF", "image", (".avif", ".avifs"),
        "AVIF: pubblicato nel 2019 dall'Alliance for Open Media, usa il codec video AV1 per ottenere immagini "
        "molto più leggere del JPEG, con HDR e trasparenza."),
    Fmt("heic", "HEIC", "image", (".heic", ".heif"),
        "HEIC/HEIF: standard MPEG del 2015 basato sul codec video HEVC; Apple lo usa per le foto degli iPhone "
        "dal 2017 (iOS 11) perché dimezza il peso rispetto al JPEG."),
    Fmt("jp2", "JPEG 2000", "image", (".jp2", ".j2k", ".jpf", ".jpx", ".j2c"),
        "JPEG 2000: standard del 2000 basato sulle wavelet e pensato come successore del JPEG; ha avuto poca "
        "fortuna sul web ma è usato nel cinema digitale, negli archivi e nei PDF."),
    Fmt("jxl", "JPEG XL", "image", (".jxl",),
        "JPEG XL: standardizzato nel 2022 per succedere al JPEG; può ricomprimere i vecchi JPEG senza perdita, "
        "ma il supporto dei browser è stato a lungo discontinuo."),
    Fmt("tga", "TGA", "image", (".tga", ".icb", ".vda", ".vst"),
        "TGA (Targa): creato da Truevision nel 1984 per le sue schede grafiche; senza perdita e con canale "
        "alfa, è ancora comune nei videogiochi e nella grafica 3D."),
    Fmt("pcx", "PCX", "image", (".pcx",),
        "PCX: nato a metà anni Ottanta con il programma PC Paintbrush di ZSoft, fu uno dei formati più "
        "diffusi su MS-DOS prima dell'arrivo di GIF e BMP."),
    Fmt("ppm", "Netpbm (PPM/PGM/PBM)", "image", (".ppm", ".pgm", ".pbm", ".pnm"),
        "Netpbm: famiglia di formati semplicissimi, quasi testo, ideati alla fine degli anni Ottanta per "
        "scambiare immagini via email tra sistemi diversi."),
    Fmt("sgi", "SGI", "image", (".sgi", ".rgb", ".bw"),
        "SGI: formato delle workstation Silicon Graphics, diffuso negli anni Ottanta e Novanta nella grafica "
        "3D e negli effetti speciali."),
    Fmt("qoi", "QOI", "image", (".qoi",),
        "QOI (Quite OK Image): ideato da Dominic Szablewski nel 2021, comprime senza perdita in modo molto "
        "veloce con una specifica lunga una sola pagina."),
    Fmt("dds", "DDS", "image", (".dds",),
        "DDS (DirectDraw Surface): formato Microsoft per le texture dei videogiochi DirectX, introdotto con "
        "DirectX 7 nel 1999."),
    Fmt("psd", "PSD", "image", (".psd",),
        "PSD: formato nativo di Adobe Photoshop dal 1990, conserva livelli ed effetti; qui viene letta "
        "l'immagine già composta, senza i livelli."),
    Fmt("xbm", "XBM", "image", (".xbm",),
        "XBM (X BitMap): nato con il sistema X Window negli anni Ottanta, è codice C che descrive un'immagine "
        "in bianco e nero; fu tra i primi formati visibili nei browser, con Mosaic nel 1993."),
    Fmt("xpm", "XPM", "image", (".xpm",),
        "XPM (X PixMap): versione a colori di XBM, creata nel 1989 per le icone delle interfacce X11; come "
        "XBM è testo C."),
    Fmt("svg", "SVG", "image", (".svg",),
        "SVG: grafica vettoriale scritta in XML, raccomandazione W3C dal 2001; si ingrandisce senza perdere "
        "nitidezza. Qui viene convertita in un'immagine a pixel."),
    # ── Documenti ─────────────────────────────────────────────
    Fmt("pdf", "PDF", "document", (".pdf",),
        "PDF: lanciato da Adobe nel 1993 per far apparire un documento identico su ogni dispositivo; è "
        "standard ISO dal 2008 (ISO 32000-1)."),
    Fmt("docx", "DOCX", "document", (".docx",),
        "DOCX: formato di Word dal 2007 (Office Open XML, standard ECMA-376 e poi ISO), un archivio ZIP di "
        "file XML che ha sostituito il vecchio binario .doc."),
    # ── Presentazioni ─────────────────────────────────────────
    Fmt("pptx", "PPTX", "slides", (".pptx",),
        "PPTX: formato di PowerPoint dal 2007, un archivio ZIP di file XML (Office Open XML) che ha "
        "sostituito il vecchio binario .ppt."),
    # ── Fogli e dati ──────────────────────────────────────────
    Fmt("xlsx", "XLSX", "sheet", (".xlsx", ".xlsm"),
        "XLSX: formato di Excel dal 2007 (ZIP di XML); porta il limite a oltre un milione di righe, contro "
        "le 65.536 del vecchio .xls."),
    Fmt("xls", "XLS", "sheet", (".xls",),
        "XLS: formato binario di Excel fino al 2003 (BIFF), limitato a 65.536 righe e 256 colonne; qui è "
        "supportato solo in lettura."),
    Fmt("csv", "CSV", "sheet", (".csv",),
        "CSV: testo semplice con i valori separati da virgole, usato già negli anni Settanta (Fortran IBM) e "
        "descritto dall'RFC 4180 nel 2005; lo leggono tutti i programmi."),
    Fmt("tsv", "TSV", "sheet", (".tsv", ".tab"),
        "TSV: come il CSV ma con le tabulazioni come separatore, più sicuro quando i dati contengono virgole "
        "o punti e virgola."),
    Fmt("json", "JSON", "sheet", (".json",),
        "JSON: formato di dati ricavato da JavaScript e reso popolare da Douglas Crockford ai primi anni "
        "Duemila; standard ECMA-404 (2013) e RFC 8259, oggi lingua franca delle API web."),
    # ── Testo e web ───────────────────────────────────────────
    Fmt("txt", "TXT", "text", (".txt", ".text", ".log"),
        "TXT: testo semplice senza formattazione, il formato più antico e portabile; oggi quasi sempre "
        "codificato in UTF-8."),
    Fmt("md", "Markdown", "text", (".md", ".markdown"),
        "Markdown: creato da John Gruber nel 2004 (con Aaron Swartz) per scrivere testo leggibile anche non "
        "formattato e convertirlo in HTML."),
    Fmt("html", "HTML", "text", (".html", ".htm", ".xhtml"),
        "HTML: il linguaggio delle pagine web, ideato da Tim Berners-Lee al CERN e descritto per la prima "
        "volta nel 1991."),
]

FORMATS = {f.key: f for f in _LIST}
_EXT = {e: f.key for f in _LIST for e in f.exts}


def key_for_path(path: str):
    """Chiave del formato dedotta dall'estensione (None se sconosciuto)."""
    return _EXT.get(os.path.splitext(path)[1].lower())


def kind_of(key):
    f = FORMATS.get(key)
    return f.kind if f else None


def label(key: str) -> str:
    f = FORMATS.get(key)
    return f.label if f else key.upper()


def blurb(key: str) -> str:
    f = FORMATS.get(key)
    return f.blurb if f else ""


def all_input_exts():
    return sorted(_EXT)

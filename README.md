# ConvertiFacile 1.1

Convertitore di file per Windows con interfaccia semplice. **Tutto in locale e senza installare altro software** (niente LibreOffice, niente Office, niente Ghostscript): solo librerie Python, incluse nell'exe.

## Cosa converte

| Famiglia | Formati | Note |
|---|---|---|
| **Immagini** | PNG, JPEG, GIF, WebP, BMP, TIFF, ICO, AVIF, HEIC, JPEG 2000, JPEG XL*, ICNS, TGA, PCX, Netpbm (PPM/PGM/PBM), QOI, XBM | scrittura e lettura |
| | CUR, SGI, DDS, PSD, XPM, SVG | sola lettura (PSD: immagine composta; SVG: rasterizzato) |
| **Documenti** | PDF, DOCX | PDF → DOCX/TXT/MD/HTML/immagini · DOCX → PDF/TXT/MD/HTML/immagini |
| **Presentazioni** | PPTX | → PDF, immagini, TXT, MD |
| **Fogli e dati** | XLSX, XLS (lettura), CSV, TSV, JSON | → tra loro, HTML e PDF |
| **Testo e web** | TXT, Markdown, HTML | → tra loro, DOCX e PDF |

\* JPEG XL richiede `pip install pillow-jxl-plugin` (facoltativo). I formati che il computer non sa leggere o scrivere vengono nascosti automaticamente.

Per ogni formato l'app mostra una frase su cos'è e sulla sua storia (selezionando un file, oppure `F1` / «Formati supportati…»).

## Cosa NON fa (di proposito)

Pochi formati, fatti bene. Non ci sono: DOC, PPT, ODT/ODS/ODP, RTF (i vecchi formati binari richiedono un motore tipo LibreOffice), OCR per PDF scansionati, EPS/WMF/EMF.

Limiti noti:
- **PPTX → PDF** ridisegna le slide da zero (testi selezionabili, immagini, forme semplici, tabelle, colori del tema). Non riproduce grafici, SmartArt, animazioni, sfumature complesse, font non standard.
- **DOCX → PDF** usa un motore HTML: titoli, stili, elenchi, tabelle e immagini sì; intestazioni/piè di pagina, note, campi e impaginazione esatta di Word no.
- **PDF → DOCX** (pdf2docx) funziona bene su PDF con testo, non su scansioni.
- Le animazioni GIF/WebP restano animate solo verso GIF o WebP; verso altri formati si salva il primo fotogramma. Un TIFF multipagina produce una cartella con una immagine per pagina.
- CSV: in uscita si può scegliere `;` (stile Excel italiano, decimali con la virgola) o `,`. In ingresso separatore e codifica (UTF-8 / Windows-1252) vengono riconosciuti da soli.

## Comportamenti utili

- Il formato di destinazione è **pre-selezionato**; si cambia con un click sulla colonna «Converti in».
- Mai sovrascrive: se esiste già, aggiunge ` (1)`, ` (2)`… (opzione per sovrascrivere).
- Rispetta l'orientamento delle foto (EXIF) e può rimuovere i metadati (GPS compreso).
- Più pagine/fogli → più file, in una cartella o con il nome del foglio nel nome.
- Errori spiegati in italiano: selezionare la riga per leggerli.

## Avvio da sorgente

```bash
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Prova di tutte le conversioni: `python selftest.py`.

## Creare l'EXE

Doppio click su `build.bat` (crea il venv, installa, esegue `selftest.py`, genera l'icona e lancia PyInstaller) → `dist\ConvertiFacile.exe`. L'avvio dell'exe singolo richiede qualche secondo (si decomprime in una cartella temporanea).

## Struttura

`app.py` avvio · `ui.py` interfaccia · `engine.py` API e instradamento · `images.py` · `docs.py` · `sheets.py` · `slides.py` · `formats.py` (catalogo + storie dei formati) · `common.py` · `icon.py` · `selftest.py`.

## Licenze

PyMuPDF è AGPL-3.0 e pdf2docx è GPL/MIT a seconda della versione: se distribuisci l'exe, tieni il codice sorgente pubblico (come questo repository) o valuta una licenza commerciale di PyMuPDF.

## Novità della 1.1

Riscrittura completa. Corretto: DOCX → PDF che non funzionava mai (`edocapi` restituisce un oggetto, non byte); PPTX → PDF con filigrana e limite di 10 slide (`pptx-raster` gratuito), ora motore proprio; HTML → TXT che non toglieva i tag; MD → HTML che metteva tutto in `<pre>`; CSV in Windows-1252 o con `;` che falliva; XLSX → PDF troncato e rasterizzato; CMYK/16 bit → PNG che andava in errore; foto ruotate; PDF multipagina → immagini; sovrascrittura silenziosa; thread che leggeva variabili Tk; interfaccia sfocata su Windows 11 (ora DPI-aware). Rimossa la dipendenza da LibreOffice.

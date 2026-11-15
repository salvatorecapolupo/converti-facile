"""Prova di tutte le conversioni: python selftest.py  (crea file di esempio in una cartella temporanea)."""
import os, sys, tempfile, time, traceback, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine, formats, images
from PIL import Image, ImageDraw


def _save_base(im, d):
    p = os.path.join(d, "_base.png"); im.save(p); return p


def main():
    root = tempfile.mkdtemp(prefix="cf-selftest-")
    src = os.path.join(root, "src"); os.makedirs(src)
    # base
    base = _save_base(Image.new("RGBA", (1, 1)), src)
    im = Image.new("RGBA", (160, 100), (255, 255, 255, 0))
    dr = ImageDraw.Draw(im); dr.ellipse((10, 10, 80, 90), fill=(220, 30, 30, 255)); dr.rectangle((70, 20, 150, 70), fill=(30, 90, 220, 180))
    im.save(base)
    # GIF animata
    frames = [Image.new("RGB", (64, 64), c) for c in ("red", "green", "blue")]
    frames[0].save(os.path.join(src, "anim.gif"), save_all=True, append_images=frames[1:], duration=120, loop=0)
    # TIFF multipagina
    frames[0].save(os.path.join(src, "multi.tif"), save_all=True, append_images=frames[1:])
    # SVG
    open(os.path.join(src, "disegno.svg"), "w").write('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="20" fill="red"/></svg>')
    # documenti
    import docx, pptx, openpyxl
    from pptx.util import Inches, Pt
    d = docx.Document(); d.add_heading("Titolo àèìòù €", 0); d.add_heading("Sezione", 1)
    p = d.add_paragraph("Testo con "); r = p.add_run("grassetto"); r.bold = True; p.add_run(" e "); r = p.add_run("corsivo"); r.italic = True
    d.add_paragraph("primo", style="List Bullet"); d.add_paragraph("secondo", style="List Bullet")
    d.add_paragraph("uno", style="List Number"); d.add_paragraph("due", style="List Number")
    t = d.add_table(rows=2, cols=2); t.style = "Table Grid"; t.cell(0, 0).text = "A"; t.cell(0, 1).text = "B"; t.cell(1, 0).text = "1"; t.cell(1, 1).text = "2"
    d.add_picture(base, width=docx.shared.Inches(1.5))
    d.save(os.path.join(src, "doc.docx"))
    pr = pptx.Presentation(); s = pr.slides.add_slide(pr.slide_layouts[1]); s.shapes.title.text = "Titolo slide"; s.placeholders[1].text = "Punto uno\nPunto due"
    s2 = pr.slides.add_slide(pr.slide_layouts[5]); s2.shapes.title.text = "Tabella"
    tb = s2.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(6), Inches(1.5)).table; tb.cell(0, 0).text = "x"; tb.cell(1, 1).text = "y"
    s2.shapes.add_picture(base, Inches(1), Inches(4), width=Inches(2))
    pr.save(os.path.join(src, "pres.pptx"))
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Dati"
    ws.append(["nome", "valore", "data"]); import datetime
    ws.append(["a", 1.5, datetime.datetime(2026, 1, 2)]); ws.append(["b", 2, datetime.datetime(2026, 3, 4, 5, 6)])
    ws2 = wb.create_sheet("Altro"); ws2.append(["x", "y"]); ws2.append([1, 2])
    wb.save(os.path.join(src, "fogli.xlsx"))
    open(os.path.join(src, "dati.csv"), "w", encoding="cp1252").write("nome;prezzo;note\nCaffè;1,50;ok\nTè;0,8;007\n")
    open(os.path.join(src, "dati.json"), "w").write('[{"a":1,"b":"x"},{"a":2,"b":"y"}]')
    open(os.path.join(src, "nota.txt"), "w", encoding="utf-8").write("Prima riga\nseconda *riga*\n\nNuovo paragrafo con # e _trattini_\n")
    open(os.path.join(src, "nota.md"), "w", encoding="utf-8").write("# Titolo\n\nTesto **forte** e *corsivo* e [link](https://example.com).\n\n- uno\n- due\n\n1. a\n2. b\n\n| x | y |\n|---|---|\n| 1 | 2 |\n\n```\ncodice\n```\n")
    open(os.path.join(src, "pagina.html"), "w", encoding="utf-8").write("<html><body><h1>Ciao</h1><p>Testo <b>bold</b> <a href='https://example.org'>link</a></p><ul><li>a</li><li>b<ul><li>b1</li></ul></li></ul><table><tr><th>h</th></tr><tr><td>c</td></tr></table></body></html>")
    # PDF di partenza (dal docx e dal pptx)
    engine.convert(os.path.join(src, "doc.docx"), "pdf", src)
    os.rename(os.path.join(src, "doc.pdf"), os.path.join(src, "documento.pdf"))
    # formati immagine di partenza
    for k in images.write_keys():
        if k not in ("png",):
            try:
                engine.convert(base, k, src)
            except Exception as e:
                print("campione", k, "NON creato:", e)
    os.rename(os.path.join(src, "_base.png"), os.path.join(src, "immagine.png"))

    files = sorted(os.listdir(src))
    ok = fail = 0
    t0 = time.time()
    for name in files:
        path = os.path.join(src, name)
        if not os.path.isfile(path):
            continue
        for tgt in engine.targets_for(path):
            out = os.path.join(root, "out", name.replace(".", "_") + "__" + tgt)
            try:
                res = engine.convert(path, tgt, out)
                bad = [r for r in res if not os.path.exists(r) or os.path.getsize(r) == 0]
                assert res and not bad, f"output mancante/vuoto {bad}"
                ok += 1
            except Exception as e:
                fail += 1
                print(f"FAIL {name} → {tgt}: {type(e).__name__}: {e}")
    print(f"\nOK: {ok}  FAIL: {fail}  ({time.time()-t0:.1f}s)  cartella: {root}")
    return fail


if __name__ == "__main__":
    sys.exit(1 if main() else 0)

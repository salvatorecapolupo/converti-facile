"""Icona dell'app, disegnata al volo (nessun file immagine da distribuire).
Eseguita direttamente crea ConvertiFacile.ico per PyInstaller."""
from PIL import Image, ImageDraw


def make_icon(size: int = 256) -> Image.Image:
    s = size * 4
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=(37, 99, 235, 255))
    w = max(4, int(s * 0.07))
    # due frecce opposte (⇄)
    y1, y2 = int(s * 0.38), int(s * 0.62)
    x0, x1 = int(s * 0.22), int(s * 0.78)
    d.line((x0, y1, x1 - int(s * .06), y1), fill="white", width=w)
    d.polygon([(x1, y1), (x1 - int(s * .13), y1 - int(s * .09)), (x1 - int(s * .13), y1 + int(s * .09))], fill="white")
    d.line((x0 + int(s * .06), y2, x1, y2), fill="white", width=w)
    d.polygon([(x0, y2), (x0 + int(s * .13), y2 - int(s * .09)), (x0 + int(s * .13), y2 + int(s * .09))], fill="white")
    return im.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    make_icon(256).save("ConvertiFacile.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("ConvertiFacile.ico creato")

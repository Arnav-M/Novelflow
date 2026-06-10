"""One-off icon generator for Novelflow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "src" / "novelflow" / "assets"
SIZE = 256


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (SIZE, SIZE), (18, 16, 26, 255))
    draw = ImageDraw.Draw(img)

    # Open book
    draw.rounded_rectangle((48, 58, 208, 198), radius=18, fill=(124, 108, 240, 255))
    draw.polygon([(128, 58), (128, 198), (48, 198), (48, 58)], fill=(108, 92, 220, 255))
    draw.polygon([(128, 58), (128, 198), (208, 198), (208, 58)], fill=(140, 124, 255, 255))
    draw.line((128, 62, 128, 194), fill=(42, 34, 72, 255), width=4)

    for y in (92, 118, 144, 170):
        draw.line((72, y, 118, y), fill=(245, 243, 255, 220), width=5)
        draw.line((138, y, 186, y), fill=(245, 243, 255, 200), width=5)

    # Flow arrow (PDF → MD)
    draw.polygon([(170, 210), (198, 226), (170, 242)], fill=(196, 181, 253, 255))
    draw.rectangle((108, 220, 172, 232), fill=(196, 181, 253, 255))

    png = OUT / "icon.png"
    ico = OUT / "icon.ico"
    img.save(png)
    img.save(ico, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Wrote {png} and {ico}")


if __name__ == "__main__":
    main()

"""
Generate default placeholder icons for the Stream Dock plugin.
Run once: python -m deckai.setup_icons
"""

from pathlib import Path
from PIL import Image, ImageDraw


PLUGIN_STATIC = Path(__file__).parent.parent / "com.deckai2.cockpit.sdPlugin" / "static"
PLUGIN_STATIC.mkdir(parents=True, exist_ok=True)

W, H = 80, 80
BG = (30, 30, 30, 255)
FG = (200, 200, 200, 255)


def make_simple_icon(text: str, color: tuple, filename: str):
    img = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(img)
    # Simple colored circle
    d.ellipse([22, 18, 58, 54], fill=color)
    # Try to get a font
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 10)
    except Exception:
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), text, font=font)
    tx = (W - bbox[2]) // 2
    d.text((tx, H - 16), text, fill=FG, font=font)
    img.save(PLUGIN_STATIC / filename)


if __name__ == "__main__":
    # Traffic light default
    make_simple_icon("TRAFFIC", (100, 100, 100, 255), "traffic-default.png")

    # Display default
    make_simple_icon("DISPLAY", (80, 80, 180, 255), "display-default.png")

    # VS Code default
    make_simple_icon("VS CODE", (0, 140, 230, 255), "vscode-default.png")

    # Plugin icon (category icon, 28x28 or similar)
    cat = Image.new("RGBA", (28, 28), (30, 30, 30, 255))
    cd = ImageDraw.Draw(cat)
    cd.ellipse([2, 2, 26, 26], fill=(0, 180, 100, 255))
    cat.save(PLUGIN_STATIC / "plugin-icon.png")

    print(f"[OK] Generated 4 default icons -> {PLUGIN_STATIC}")

"""
DeckAI Image Generator
Generates LCD button images for the Stream Dock N3/N3e (80×80 px).
"""

import base64
import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Stream Dock N3 LCD button resolution
W, H = 80, 80

STATIC_DIR = Path(__file__).parent / "static" / "buttons"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# --- Color palette (dark theme, modern) ---

BG_DARK = (30, 30, 30, 255)
TEXT_WHITE = (240, 240, 240, 255)
TEXT_DIM = (120, 120, 120, 255)
ACCENT_BLUE = (0, 150, 255, 255)
ACCENT_PURPLE = (160, 80, 255, 255)
VSCODE_BLUE = (0, 120, 220)


def _get_font(size: int):
    """Try to get a nice font, fall back to default."""
    font_paths = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/seguiemj.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/SFNSDisplay.ttf",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


# --- Traffic light: full-button color, no text ---

def make_traffic_full(color: str, active: bool) -> Image.Image:
    """Full-button color. Active = bright, inactive = dimmed."""
    colors_active = {
        "green": (0, 255, 100, 255),
        "yellow": (255, 190, 0, 255),
        "red": (255, 40, 40, 255),
    }
    colors_inactive = {
        "green": (35, 55, 40, 255),
        "yellow": (50, 45, 25, 255),
        "red": (55, 30, 30, 255),
    }
    bg = colors_active[color] if active else colors_inactive[color]
    return Image.new("RGBA", (W, H), bg)


# --- Mode display: small dim labels, NO large foreground value ---

def make_mode_button(label: str, value: str, accent_color: tuple = ACCENT_BLUE) -> Image.Image:
    """Clean centered text: LABEL on top, value below (auto-split long lines)."""
    img = Image.new("RGBA", (W, H), BG_DARK)
    d = ImageDraw.Draw(img)

    # Label at top
    d.text((W // 2, 12), label, fill=accent_color, font=_get_font(8), anchor="mt")

    # Value: split into max 2 lines if too long, adjust font size
    words = value.split(" ")
    font_size = 11 if len(value) < 14 else 9
    font = _get_font(font_size)

    if len(value) > 14 and len(words) >= 3:
        # Two-line: split roughly in half
        mid = len(words) // 2
        line1 = " ".join(words[:mid])
        line2 = " ".join(words[mid:])
        d.text((W // 2, 36), line1, fill=TEXT_WHITE, font=font, anchor="mt")
        d.text((W // 2, 50), line2, fill=TEXT_WHITE, font=font, anchor="mt")
    else:
        d.text((W // 2, 42), value, fill=TEXT_WHITE, font=font, anchor="mt")

    return img


# --- VS Code: original design minus the big "VS CODE" text ---

def make_vscode_button() -> Image.Image:
    """VS Code focus button with icon and small FOCUS label."""
    img = Image.new("RGBA", (W, H), BG_DARK)
    d = ImageDraw.Draw(img)

    # Blue accent border
    d.rounded_rectangle([18, 16, W - 18, H - 16], radius=8, outline=VSCODE_BLUE, width=2)

    # ">" angle bracket icon
    pts = [(30, 26), (48, 40), (30, 54)]
    d.line(pts, fill=VSCODE_BLUE, width=3, joint="curve")

    # Small "FOCUS" label at top
    d.text((W // 2, 18), "FOCUS", fill=VSCODE_BLUE, font=_get_font(8), anchor="mt")

    return img


# --- Bulk generation ---

def generate_all() -> dict[str, bytes]:
    """Generate all button images. Returns {name: png_bytes}."""
    results = {}

    # Traffic lights: active bright, inactive dimmed
    for color in ("green", "yellow", "red"):
        for state in ("active", "inactive"):
            img = make_traffic_full(color, state == "active")
            buf = io.BytesIO()
            img.save(buf, "PNG")
            results[f"traffic_{color}_{state}"] = buf.getvalue()

    # VS Code
    img = make_vscode_button()
    buf = io.BytesIO()
    img.save(buf, "PNG")
    results["vscode_focus"] = buf.getvalue()

    # Mode/Effort variants
    from .state import EFFORT_LEVELS, WORK_MODES

    for effort in EFFORT_LEVELS:
        img = make_mode_button("EFFORT", effort, ACCENT_BLUE)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        results[f"effort_{effort}"] = buf.getvalue()

    for mode in WORK_MODES:
        img = make_mode_button("MODE", mode, ACCENT_PURPLE)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        results[f"mode_{mode}"] = buf.getvalue()

    return results


def get_button_png_base64(name: str) -> str:
    """Get a single button image as base64 PNG string."""
    img = None
    buf = io.BytesIO()

    if name.startswith("traffic_"):
        parts = name.split("_", 2)
        if len(parts) >= 3:
            color, state = parts[1], parts[2]
            img = make_traffic_full(color, state == "active")
        else:
            img = make_traffic_full(parts[1], True)
    elif name == "vscode_focus":
        img = make_vscode_button()
    elif name.startswith("effort_"):
        value = name.split("_", 1)[1]
        img = make_mode_button("EFFORT", value, ACCENT_BLUE)
    elif name.startswith("mode_"):
        value = name.split("_", 1)[1]
        img = make_mode_button("MODE", value, ACCENT_PURPLE)
    else:
        img = Image.new("RGBA", (W, H), BG_DARK)

    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def save_all_to_disk():
    """Pre-generate all button images to disk for the Stream Dock plugin."""
    images = generate_all()
    for name, data in images.items():
        path = STATIC_DIR / f"{name}.png"
        path.write_bytes(data)
    print(f"[DeckAI] Generated {len(images)} button images -> {STATIC_DIR}")


if __name__ == "__main__":
    save_all_to_disk()

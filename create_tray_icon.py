import contextlib
import os

from PIL import Image, ImageDraw, ImageFont

# state → (circle_color, filename)
_STATES = {
    "default": ((52, 152, 219), "default.png"),  # Blue
    "proxy_only": ((243, 156, 18), "proxy_only.png"),  # Orange/amber
    "disabled": ((219, 52, 52), "disabled.png"),  # Red
}


def create_tray_icon(state: str = "default"):
    """Create a P99 tray icon PNG for the given proxy state.

    Args:
        state: One of "default", "proxy_only", or "disabled".
    """
    color, filename = _STATES[state]

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    circle_radius = size // 2
    circle_center = (size // 2, size // 2)
    circle_bbox = [
        circle_center[0] - circle_radius,
        circle_center[1] - circle_radius,
        circle_center[0] + circle_radius,
        circle_center[1] + circle_radius,
    ]

    circle_fill = (*color, 200)
    draw.ellipse(circle_bbox, fill=circle_fill, outline=color, width=2)

    font = None
    font_position_mod = 2
    try:
        potential_fonts = [
            ("C:\\Windows\\Fonts\\lucon.ttf", 1.5, 2),
            ("C:\\Windows\\Fonts\\arialbd.ttf", 1.7, 1.3),
            ("C:\\Windows\\Fonts\\impact.ttf", 1.5, 1.3),
        ]
        for path, scale, pos_mod in potential_fonts:
            if os.path.exists(path):
                font = ImageFont.truetype(path, size=int(circle_radius * scale))
                font_position_mod = pos_mod
                break
    except Exception:
        pass
    if font is None:
        font = ImageFont.load_default()

    text = "99"
    try:
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
    except AttributeError:
        text_width, text_height = draw.textsize(text, font=font)

    text_position = (circle_center[0] - text_width // 2, circle_center[1] - text_height // font_position_mod)

    shadow_offset = 1
    draw.text(
        (text_position[0] + shadow_offset, text_position[1] + shadow_offset), text, fill=(0, 0, 0, 128), font=font
    )
    draw.text(text_position, text, fill=(255, 255, 255), font=font)

    icon_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "p99_sso_login_proxy", "icons", "p99")
    os.makedirs(icon_dir, exist_ok=True)
    icon_path = os.path.join(icon_dir, filename)

    if os.path.exists(icon_path):
        with contextlib.suppress(BaseException):
            os.remove(icon_path)

    image.save(icon_path)
    return icon_path


if __name__ == "__main__":
    for s in _STATES:
        p = create_tray_icon(s)
        print(f"Created {p}")

import os

from PIL import Image, ImageDraw, ImageFont


def create_tray_icon(disabled=False):
    """Create a tray icon image with a circle and '99' text
    
    Args:
        disabled (bool): If True, creates a red-tinted version of the icon
    """
    # Create a new image with a transparent background
    size = 64
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Choose color based on disabled status
    if disabled:
        # Red color for disabled state
        color = (219, 52, 52)  # Red
        filename = "tray_icon_disabled.png"
    else:
        # Blue color for normal state
        color = (52, 152, 219)  # Blue
        filename = "tray_icon.png"
    
    # Draw a circle
    circle_margin = 0
    circle_radius = (size - 2 * circle_margin) // 2
    circle_center = (size // 2, size // 2)
    circle_bbox = [
        circle_center[0] - circle_radius,
        circle_center[1] - circle_radius,
        circle_center[0] + circle_radius,
        circle_center[1] + circle_radius
    ]
    
    # Draw filled circle with some transparency
    circle_fill = color + (200,)  # Add alpha channel (200/255 opacity)
    draw.ellipse(circle_bbox, fill=circle_fill, outline=color, width=2)
    
    # Try to load a font, fall back to default if not available
    try:
        # Try to find a bold font for the text
        font_path = None
        # Common font locations
        potential_fonts = [
            ("C:\\Windows\\Fonts\\lucon.ttf", 1.5, 2),      # Lucida Console
            ("C:\\Windows\\Fonts\\arialbd.ttf", 1.7, 1.3),  # Arial Bold
            ("C:\\Windows\\Fonts\\impact.ttf", 1.5, 1.3),   # Impact Regular
        ]
        
        for path, scale, position_mod in potential_fonts:
            if os.path.exists(path):
                font_path = path
                font_scale = scale
                font_position_mod = position_mod
                break
        
        if font_path:
            # Increase font size by 40% for better visibility
            font_size = int(circle_radius * font_scale)
            font = ImageFont.truetype(font_path, size=font_size)
        else:
            # Fall back to default font
            font = ImageFont.load_default()
    except Exception:
        # If any error occurs with fonts, use default
        font = ImageFont.load_default()
    
    # Draw "99" text in white
    text = "99"
    text_color = (255, 255, 255)  # White
    
    # Get text size to center it
    try:
        # For newer Pillow versions
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
    except AttributeError:
        # For older Pillow versions
        text_width, text_height = draw.textsize(text, font=font)
    
    text_position = (
        circle_center[0] - text_width // 2,
        circle_center[1] - text_height // font_position_mod
    )
    
    # Draw text with a slight shadow for better visibility
    shadow_offset = 1
    draw.text((text_position[0] + shadow_offset, text_position[1] + shadow_offset), 
              text, fill=(0, 0, 0, 128), font=font)  # Semi-transparent black shadow
    draw.text(text_position, text, fill=text_color, font=font)
    
    # Save the image
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    
    # Force the icon to be recreated by deleting any existing icon first
    if os.path.exists(icon_path):
        try:
            os.remove(icon_path)
        except:
            pass
    
    image.save(icon_path)
    return icon_path
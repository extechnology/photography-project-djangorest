import io
import math
import os
from PIL import Image, ImageDraw, ImageFont, ImageEnhance


def stamp_watermark_on_image(
    image_file,
    watermark_text: str = '',
    logo_file=None,
    opacity: float = 0.45,
    position: str = 'bottom-right',
    quality: int = 95,
    watermark_image_path=None,
) -> io.BytesIO:
    """
    Stamps typographic or logo watermark onto an image using Pillow.
    Returns BytesIO object containing the stamped JPEG.
    """
    # 0. Resolve image stream/bytes
    if isinstance(image_file, (bytes, bytearray)):
        image_stream = io.BytesIO(image_file)
    elif hasattr(image_file, 'read'):
        if hasattr(image_file, 'seek'):
            try:
                image_file.seek(0)
            except Exception:
                pass
        image_stream = image_file
    elif isinstance(image_file, str) and os.path.exists(image_file):
        image_stream = image_file
    else:
        image_stream = image_file

    base = Image.open(image_stream).convert('RGBA')
    width, height = base.size

    # Create transparent watermark overlay
    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Normalize position
    pos_norm = str(position or 'bottom-right').replace('_', '-').strip().lower()
    if pos_norm in ('repeat', 'repeated'):
        pos_norm = 'tiled'

    # Normalize opacity
    try:
        eff_opacity = max(0.05, min(1.0, float(opacity if opacity is not None else 0.45)))
    except (ValueError, TypeError):
        eff_opacity = 0.45

    # 1. Custom Logo Stamp
    actual_logo = logo_file if logo_file is not None else watermark_image_path
    logo_drawn = False

    if actual_logo:
        try:
            if isinstance(actual_logo, (str, os.PathLike)) and os.path.exists(str(actual_logo)):
                logo = Image.open(str(actual_logo)).convert('RGBA')
            elif hasattr(actual_logo, 'read'):
                if hasattr(actual_logo, 'seek'):
                    try:
                        actual_logo.seek(0)
                    except Exception:
                        pass
                logo = Image.open(actual_logo).convert('RGBA')
            elif isinstance(actual_logo, Image.Image):
                logo = actual_logo.convert('RGBA')
            else:
                logo = None

            if logo:
                max_w = max(24, int(width * 0.22))
                max_h = max(24, int(height * 0.18))
                logo.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

                # Adjust logo opacity
                alpha = logo.split()[3]
                alpha = ImageEnhance.Brightness(alpha).enhance(eff_opacity)
                logo.putalpha(alpha)

                pad = max(24, int(min(width, height) * 0.035))
                lw, lh = logo.size

                if pos_norm == 'bottom-left':
                    pos = (pad, height - lh - pad)
                elif pos_norm == 'top-right':
                    pos = (width - lw - pad, pad)
                elif pos_norm == 'top-left':
                    pos = (pad, pad)
                elif pos_norm == 'center':
                    pos = ((width - lw) // 2, (height - lh) // 2)
                elif pos_norm == 'tiled':
                    step_x = max(int(lw * 2.2), 260)
                    step_y = max(int(lh * 2.2), 160)
                    for x in range(0, width, step_x):
                        for y in range(0, height, step_y):
                            overlay.paste(logo, (x, y), logo)
                    pos = None
                else:  # bottom-right
                    pos = (width - lw - pad, height - lh - pad)

                if pos:
                    overlay.paste(logo, pos, logo)
                logo_drawn = True
        except Exception:
            logo_drawn = False

    # 2. Typographic Watermark Stamp
    if not logo_drawn:
        raw_text = (watermark_text or '').strip()
        text = raw_text if raw_text else 'PHOTOGRAPHER'
        min_dim = min(width, height)

        if pos_norm == 'center':
            font_size = max(32, int(min_dim * 0.055))
        elif pos_norm == 'tiled':
            font_size = max(18, int(min_dim * 0.028))
        else:
            font_size = max(24, int(min_dim * 0.035))

        font = None
        font_candidates = [
            "arial.ttf",
            "Arial.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
        for candidate in font_candidates:
            try:
                font = ImageFont.truetype(candidate, font_size)
                break
            except (IOError, OSError):
                continue

        if not font:
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None

        # Calculate text bounding box
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except Exception:
            tw = int(font_size * len(text) * 0.6)
            th = font_size

        pad = max(24, int(min_dim * 0.035))
        if pos_norm == 'bottom-left':
            tx, ty = pad, height - th - pad
        elif pos_norm == 'top-right':
            tx, ty = width - tw - pad, pad
        elif pos_norm == 'top-left':
            tx, ty = pad, pad
        elif pos_norm == 'center':
            tx, ty = (width - tw) // 2, (height - th) // 2
        else:  # bottom-right
            tx, ty = width - tw - pad, height - th - pad

        # Stamp shadow / outline for high contrast across dark and light photos
        alpha_int = int(eff_opacity * 255)
        shadow_alpha = min(220, int(eff_opacity * 320))
        outline_color = (0, 0, 0, shadow_alpha)
        text_color = (255, 255, 255, alpha_int)
        stroke_width = max(2, int(font_size * 0.08))

        if pos_norm == 'tiled':
            step_x = max(int(font_size * 12), 300)
            step_y = max(int(font_size * 6), 150)
            for x in range(-width // 2, width * 2, step_x):
                for y in range(-height // 2, height * 2, step_y):
                    try:
                        draw.text((x, y), text, font=font, fill=text_color, stroke_width=stroke_width, stroke_fill=outline_color)
                    except TypeError:
                        draw.text((x + 2, y + 2), text, font=font, fill=outline_color)
                        draw.text((x, y), text, font=font, fill=text_color)
        else:
            try:
                draw.text((tx, ty), text, font=font, fill=text_color, stroke_width=stroke_width, stroke_fill=outline_color)
            except TypeError:
                draw.text((tx + 2, ty + 2), text, font=font, fill=outline_color)
                draw.text((tx, ty), text, font=font, fill=text_color)

    combined = Image.alpha_composite(base, overlay)
    out = io.BytesIO()
    combined.convert('RGB').save(out, format='JPEG', quality=quality, optimize=True)
    out.seek(0)
    return out

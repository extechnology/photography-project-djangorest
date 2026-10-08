import io
import math
import os
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageColor

__all__ = ['stamp_watermark_on_image', 'apply_watermark', 'hex_to_rgba']


def hex_to_rgba(hex_code, opacity=1.0):
    """
    Converts a hex color code (e.g. '#FFFFFF', '#D4AF37') and opacity float
    into an (R, G, B, A) 4-tuple.
    """
    hex_code = (hex_code or '#FFFFFF').lstrip('#')
    if len(hex_code) == 3:
        hex_code = ''.join([c * 2 for c in hex_code])
    try:
        r, g, b = ImageColor.getrgb(f"#{hex_code}")
    except Exception:
        r, g, b = (255, 255, 255)
    alpha = int(max(0.05, min(1.0, float(opacity if opacity is not None else 1.0))) * 255)
    return (r, g, b, alpha)


def _resolve_font(font_style: str, font_px: int) -> ImageFont.ImageFont:
    """
    Resolves a TrueType font for the given style preset ('serif', 'sans', 'script', 'mono')
    across local assets and Windows / Linux system directories.
    """
    style = str(font_style or 'serif').lower().strip()
    font_px = max(12, int(font_px))

    # Candidate fonts by priority
    style_candidates = {
        'serif': [
            "assets/fonts/Cinzel-SemiBold.ttf",
            "assets/fonts/PlayfairDisplay-Regular.ttf",
            "times.ttf",
            "timesbd.ttf",
            "georgia.ttf",
            "georgiab.ttf",
            "C:/Windows/Fonts/times.ttf",
            "C:/Windows/Fonts/georgia.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
        ],
        'sans': [
            "assets/fonts/Inter-Bold.ttf",
            "arial.ttf",
            "arialbd.ttf",
            "calibri.ttf",
            "calibrib.ttf",
            "segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ],
        'script': [
            "assets/fonts/PlayfairDisplay-Italic.ttf",
            "assets/fonts/GreatVibes-Regular.ttf",
            "segoesc.ttf",
            "comic.ttf",
            "BRUSHSCI.TTF",
            "georgiai.ttf",
            "timesi.ttf",
            "C:/Windows/Fonts/segoesc.ttf",
            "C:/Windows/Fonts/comic.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
        ],
        'mono': [
            "assets/fonts/JetBrainsMono-Medium.ttf",
            "consola.ttf",
            "consolab.ttf",
            "cour.ttf",
            "courbd.ttf",
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/cour.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        ],
    }

    candidates = style_candidates.get(style, style_candidates['serif'])
    # Add generic fallbacks
    candidates += [
        "arial.ttf",
        "Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    for path in candidates:
        try:
            return ImageFont.truetype(path, font_px)
        except (IOError, OSError):
            continue

    try:
        return ImageFont.load_default()
    except Exception:
        return None


def apply_watermark(base_image: Image.Image, profile) -> Image.Image:
    """
    Applies either image logo OR text watermark with full font color & style support.
    Enforces STRICT ONE-AT-A-TIME mode:
      - If watermark_type == 'text': ONLY custom text is stamped with selected font, color, and size.
        Logo is completely ignored, even if a logo file exists.
      - If watermark_type == 'image': ONLY the uploaded logo image is stamped.
      - If unspecified, defaults strictly to 'text'.
    
    Accepts profile as a PhotographerProfile model, Gallery model, or config dict.
    """
    def _get_val(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    if not profile or not _get_val(profile, 'enable_watermark', True):
        return base_image

    img = base_image.convert("RGBA")
    width, height = img.size
    min_dim = min(width, height)
    opacity = float(_get_val(profile, 'watermark_opacity', 0.45) or 0.45)
    position = str(_get_val(profile, 'watermark_position', 'bottom-right') or 'bottom-right').replace('_', '-').strip().lower()
    if position in ('repeat', 'repeated'):
        position = 'tiled'

    raw_wm_type = _get_val(profile, 'watermark_type', 'text')
    watermark_type = str(raw_wm_type or 'text').lower().strip()
    if watermark_type != 'image':
        watermark_type = 'text'

    logo_file = _get_val(profile, 'watermark_image', None) if watermark_type == 'image' else None

    # ─────────────────────────────────────────────────────────────
    # MODE 1: IMAGE LOGO WATERMARK (Strictly active only if watermark_type == 'image')
    # ─────────────────────────────────────────────────────────────
    if watermark_type == 'image' and logo_file:
        try:
            if hasattr(logo_file, 'seek'):
                try:
                    logo_file.seek(0)
                except Exception:
                    pass
                logo = Image.open(logo_file).convert("RGBA")
            elif hasattr(logo_file, 'path') and os.path.exists(logo_file.path):
                logo = Image.open(logo_file.path).convert("RGBA")
            elif isinstance(logo_file, (str, os.PathLike)) and os.path.exists(str(logo_file)):
                logo = Image.open(str(logo_file)).convert("RGBA")
            elif isinstance(logo_file, Image.Image):
                logo = logo_file.convert("RGBA")
            else:
                logo = None

            if logo:
                # Scale logo proportionally (~18% of photo dimension, max 22% width)
                max_logo_w = max(24, int(width * 0.22))
                max_logo_h = max(24, int(height * 0.18))
                logo.thumbnail((max_logo_w, max_logo_h), Image.Resampling.LANCZOS)

                # Apply alpha opacity
                r, g, b, a = logo.split()
                a = a.point(lambda p: int(p * opacity))
                logo.putalpha(a)

                padding = max(24, int(min_dim * 0.035))
                lw, lh = logo.size

                if position == 'bottom-left':
                    pos = (padding, height - lh - padding)
                elif position == 'top-right':
                    pos = (width - lw - padding, padding)
                elif position == 'top-left':
                    pos = (padding, padding)
                elif position == 'center':
                    pos = ((width - lw) // 2, (height - lh) // 2)
                elif position == 'tiled':
                    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                    step_x = max(int(lw * 2.2), 300)
                    step_y = max(int(lh * 2.2), 200)
                    for x in range(0, width, step_x):
                        for y in range(0, height, step_y):
                            overlay.alpha_composite(logo, (x, y))
                    return Image.alpha_composite(img, overlay).convert(base_image.mode)
                else:  # 'bottom-right'
                    pos = (width - lw - padding, height - lh - padding)

                img.alpha_composite(logo, pos)
                return img.convert(base_image.mode)
        except Exception:
            # Fallback to text if logo loading fails
            pass

    # ─────────────────────────────────────────────────────────────
    # MODE 2: TEXT SIGNATURE WATERMARK (Strict font color & style)
    # ─────────────────────────────────────────────────────────────
    font_style = _get_val(profile, 'watermark_font_style', 'serif') or 'serif'

    raw_text = ''
    if not isinstance(profile, dict) and hasattr(profile, 'get_watermark_text'):
        raw_text = profile.get_watermark_text()
    elif not isinstance(profile, dict) and hasattr(profile, 'get_effective_watermark_text'):
        raw_text = profile.get_effective_watermark_text()
    if not raw_text:
        raw_text = _get_val(profile, 'watermark_text', '© STUDIO') or '© STUDIO'
    raw_text = str(raw_text).strip()

    # Capitalize for script calligraphy, uppercase for serif/sans/mono
    text = raw_text if font_style == 'script' else raw_text.upper()

    size_preset = _get_val(profile, 'watermark_font_size', 'md') or 'md'
    font_multipliers = {'sm': 0.024, 'md': 0.034, 'lg': 0.046, 'xl': 0.060}
    font_px = max(18, int(min_dim * font_multipliers.get(size_preset, 0.034)))
    if font_style == 'script':
        font_px = int(font_px * 1.3)
    if position == 'center':
        font_px = int(font_px * 1.35)

    font = _resolve_font(font_style, font_px)

    font_color_hex = str(_get_val(profile, 'watermark_font_color', '#FFFFFF') or '#FFFFFF')
    fill_rgba = hex_to_rgba(font_color_hex, opacity)

    # Adaptive contrast shadow based on text color
    is_dark_font = font_color_hex.lower().strip() in ['#000000', '#18181b', '#111827', '#222222', '#333333']
    shadow_rgba = (255, 255, 255, int(opacity * 200)) if is_dark_font else (0, 0, 0, int(opacity * 230))

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    padding = max(24, int(min_dim * 0.035))
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw = int(font_px * len(text) * 0.6)
        th = font_px

    if position == 'bottom-left':
        x, y = padding, height - th - padding
    elif position == 'top-right':
        x, y = width - tw - padding, padding
    elif position == 'top-left':
        x, y = padding, padding
    elif position == 'center':
        x, y = (width - tw) // 2, (height - th) // 2
    elif position == 'tiled':
        tiled_layer = Image.new("RGBA", (int(width * 1.6), int(height * 1.6)), (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(tiled_layer)
        step_x = max(int(tw * 1.6), 340)
        step_y = max(int(font_px * 6), 180)
        for tx in range(0, tiled_layer.width, step_x):
            for ty in range(0, tiled_layer.height, step_y):
                t_draw.text((tx + 2, ty + 2), text, font=font, fill=shadow_rgba)
                t_draw.text((tx, ty), text, font=font, fill=fill_rgba)
        rotated = tiled_layer.rotate(28, resample=Image.Resampling.BICUBIC)
        rw, rh = rotated.size
        crop_box = ((rw - width) // 2, (rh - height) // 2, (rw + width) // 2, (rh + height) // 2)
        cropped = rotated.crop(crop_box)
        return Image.alpha_composite(img, cropped).convert(base_image.mode)
    else:  # 'bottom-right'
        x, y = width - tw - padding, height - th - padding

    # Drop shadow stroke + primary fill for crisp legibility
    draw.text((x + 2, y + 2), text, font=font, fill=shadow_rgba)
    draw.text((x, y), text, font=font, fill=fill_rgba)

    return Image.alpha_composite(img, overlay).convert(base_image.mode)


def stamp_watermark_on_image(
    image_file,
    watermark_text: str = '',
    logo_file=None,
    opacity: float = 0.45,
    position: str = 'bottom-right',
    quality: int = 95,
    watermark_image_path=None,
    font_style: str = 'serif',
    font_size: str = 'md',
    font_color: str = '#FFFFFF',
    watermark_type: str = None,
) -> io.BytesIO:
    """
    Stamps typographic or logo watermark onto an image using Pillow.
    Strictly defaults watermark_type to 'text' if not explicitly 'image'.
    Returns BytesIO object containing the stamped JPEG.
    """
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

    base = Image.open(image_stream).convert('RGB')

    # STRICT ONE-AT-A-TIME: Defaults strictly to 'text'. Never default to 'image' just because logo exists!
    effective_wm_type = (watermark_type or 'text').lower().strip()
    if effective_wm_type not in ('text', 'image'):
        effective_wm_type = 'text'

    actual_logo = None
    if effective_wm_type == 'image':
        actual_logo = logo_file if logo_file is not None else watermark_image_path

    # Construct synthetic profile wrapper for apply_watermark
    class _WatermarkConfigWrapper:
        pass

    cfg = _WatermarkConfigWrapper()
    cfg.enable_watermark = True
    cfg.watermark_type = effective_wm_type
    cfg.watermark_text = watermark_text
    cfg.watermark_image = actual_logo
    cfg.watermark_opacity = opacity
    cfg.watermark_position = position
    cfg.watermark_font_size = font_size
    cfg.watermark_font_color = font_color
    cfg.watermark_font_style = font_style

    stamped = apply_watermark(base, cfg)

    out = io.BytesIO()
    stamped.convert('RGB').save(out, format='JPEG', quality=quality, optimize=True)
    out.seek(0)
    return out

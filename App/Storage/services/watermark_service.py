import io
from PIL import Image, ImageDraw, ImageFont, ImageEnhance


class WatermarkService:
    """
    Renders dynamic studio typography or PNG stamp watermarks
    onto client-facing media derivatives.
    """

    @classmethod
    def apply_watermark(cls, base_image: Image.Image, photographer_profile) -> Image.Image:
        if not photographer_profile or not getattr(photographer_profile, 'enable_watermark', False):
            return base_image

        try:
            # Ensure base image is in RGBA for clean alpha compositing
            working_img = base_image.convert("RGBA")
            overlay = Image.new("RGBA", working_img.size, (255, 255, 255, 0))

            watermark_image_field = getattr(photographer_profile, 'watermark_image', None)
            watermark_text = getattr(photographer_profile, 'watermark_text', '') or "© Studio"
            opacity = float(getattr(photographer_profile, 'watermark_opacity', 0.45))
            position = getattr(photographer_profile, 'watermark_position', 'bottom_right')

            width, height = working_img.size

            if watermark_image_field and hasattr(watermark_image_field, 'read'):
                # PNG Logo Stamp
                try:
                    watermark_image_field.seek(0)
                    wm_logo = Image.open(watermark_image_field).convert("RGBA")
                    # Scale watermark logo to max 25% of image width
                    target_w = int(width * 0.25)
                    aspect = wm_logo.height / max(1, wm_logo.width)
                    target_h = int(target_w * aspect)
                    wm_logo = wm_logo.resize((max(40, target_w), max(40, target_h)), Image.Resampling.LANCZOS)

                    # Adjust opacity
                    alpha = wm_logo.split()[3]
                    alpha = ImageEnhance.Brightness(alpha).enhance(opacity)
                    wm_logo.putalpha(alpha)

                    # Position
                    pos_x, pos_y = cls._calculate_coordinates(width, height, wm_logo.width, wm_logo.height, position)
                    overlay.paste(wm_logo, (pos_x, pos_y), wm_logo)
                    combined = Image.alpha_composite(working_img, overlay)
                    return combined.convert("RGB")
                except Exception:
                    # Fallback to text watermark
                    pass

            # Typography Watermark
            draw = ImageDraw.Draw(overlay)
            font_size = max(16, int(height * 0.035))
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()

            # Measure text size
            bbox = draw.textbbox((0, 0), watermark_text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            text_color = (255, 255, 255, int(255 * opacity))
            shadow_color = (0, 0, 0, int(180 * opacity))

            if position == 'repeated':
                step_x = max(150, int(text_w * 2.2))
                step_y = max(100, int(text_h * 4.0))
                for y in range(40, height, step_y):
                    for x in range(40, width, step_x):
                        draw.text((x + 1, y + 1), watermark_text, font=font, fill=shadow_color)
                        draw.text((x, y), watermark_text, font=font, fill=text_color)
            else:
                pos_x, pos_y = cls._calculate_coordinates(width, height, text_w, text_h, position)
                draw.text((pos_x + 1, pos_y + 1), watermark_text, font=font, fill=shadow_color)
                draw.text((pos_x, pos_y), watermark_text, font=font, fill=text_color)

            combined = Image.alpha_composite(working_img, overlay)
            return combined.convert("RGB")

        except Exception:
            return base_image

    @staticmethod
    def _calculate_coordinates(img_w, img_h, item_w, item_h, position):
        padding_x = int(img_w * 0.04)
        padding_y = int(img_h * 0.04)

        if position == 'center':
            return (img_w - item_w) // 2, (img_h - item_h) // 2
        elif position == 'bottom_left':
            return padding_x, img_h - item_h - padding_y
        elif position == 'top_right':
            return img_w - item_w - padding_x, padding_y
        else:  # default bottom_right
            return img_w - item_w - padding_x, img_h - item_h - padding_y

import io
from PIL import Image
from utils.watermark import stamp_watermark_on_image, apply_watermark, hex_to_rgba

__all__ = ['WatermarkService', 'stamp_watermark_on_image', 'apply_watermark', 'hex_to_rgba']


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
            return apply_watermark(base_image, photographer_profile)
        except Exception:
            return base_image

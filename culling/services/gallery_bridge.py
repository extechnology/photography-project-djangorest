"""
Compatibility module mapping culling.services.gallery_bridge to App.Culling.services.gallery_bridge
"""
from App.Culling.services.gallery_bridge import (
    move_culled_photos_to_gallery,
    execute_move_to_gallery,
)

__all__ = [
    'move_culled_photos_to_gallery',
    'execute_move_to_gallery',
]

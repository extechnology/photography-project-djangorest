"""
App.Culling.services.move_service
Compatibility re-exports from .gallery_bridge
"""
from .gallery_bridge import (
    move_culled_photos_to_gallery,
    execute_move_to_gallery,
)

__all__ = [
    'move_culled_photos_to_gallery',
    'execute_move_to_gallery',
]

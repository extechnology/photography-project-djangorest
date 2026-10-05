from typing import List, Optional
from django.db import transaction
from rest_framework.exceptions import ValidationError
from gallery.models import Gallery, GalleryMedia


@transaction.atomic
def reorder_gallery_media(
    gallery: Gallery,
    media_ids: Optional[List[str]] = None,
    media_id: Optional[str] = None,
    action: Optional[str] = None,
    target_position: Optional[int] = None
) -> int:
    """
    High-performance atomic reordering service supporting:
    1. Full sequence list: media_ids = [id1, id2, ...]
    2. Single or batch action: action='top' | 'bottom' | 'position'
    """
    # Fetch all current active media items for this gallery
    media_manager = getattr(gallery, 'media', None) or getattr(gallery, 'media_items', None)
    if hasattr(media_manager, 'filter'):
        existing_items = list(media_manager.filter(deleted_at__isnull=True).order_by('order', 'created_at'))
        if not existing_items:
            existing_items = list(media_manager.all().order_by('order', 'created_at'))
    else:
        existing_items = list(GalleryMedia.objects.filter(gallery=gallery, deleted_at__isnull=True).order_by('order', 'created_at'))

    if not existing_items:
        return 0

    item_map = {str(item.id): item for item in existing_items}
    ordered_items = list(existing_items)

    # -------------------------------------------------------------
    # CASE 1: Single item jump to Top / Bottom / Custom Position
    # -------------------------------------------------------------
    if media_id and action:
        str_id = str(media_id)
        if str_id not in item_map:
            raise ValidationError(f"Media item with ID '{media_id}' does not exist in this gallery.")

        target_item = item_map[str_id]
        ordered_items.remove(target_item)

        if action == 'top':
            ordered_items.insert(0, target_item)
        elif action == 'bottom':
            ordered_items.append(target_item)
        elif action == 'position':
            # target_position is 1-based index (1 = first)
            pos = 1 if target_position is None else max(1, min(len(existing_items), int(target_position)))
            ordered_items.insert(pos - 1, target_item)
        else:
            raise ValidationError(f"Invalid action '{action}'. Choose from: 'top', 'bottom', 'position'.")

    # -------------------------------------------------------------
    # CASE 2: Batch items jump to Top / Bottom
    # -------------------------------------------------------------
    elif media_ids and action in ['top', 'bottom']:
        selected_set = set(str(mid) for mid in media_ids)
        selected_items = [item for item in ordered_items if str(item.id) in selected_set]
        non_selected = [item for item in ordered_items if str(item.id) not in selected_set]

        if action == 'top':
            ordered_items = selected_items + non_selected
        else:
            ordered_items = non_selected + selected_items

    # -------------------------------------------------------------
    # CASE 3: Full media_ids array specified by client
    # -------------------------------------------------------------
    elif media_ids:
        new_ordered = []
        seen = set()

        for mid in media_ids:
            str_mid = str(mid)
            if str_mid in item_map and str_mid not in seen:
                new_ordered.append(item_map[str_mid])
                seen.add(str_mid)

        # Append any items that were omitted from media_ids at the end
        for item in existing_items:
            if str(item.id) not in seen:
                new_ordered.append(item)

        ordered_items = new_ordered

    else:
        raise ValidationError("Must provide 'media_ids' list or 'media_id' with an 'action'.")

    # -------------------------------------------------------------
    # Atomic Bulk Update in Database
    # -------------------------------------------------------------
    items_to_update = []
    for idx, item in enumerate(ordered_items, start=0):
        if getattr(item, 'order', None) != idx or getattr(item, 'display_order', None) != idx:
            item.order = idx
            item.display_order = idx
            items_to_update.append(item)

    if items_to_update:
        fields = ['order']
        if hasattr(items_to_update[0], 'display_order'):
            fields.append('display_order')
        GalleryMedia.objects.bulk_update(items_to_update, fields)

    return len(items_to_update)

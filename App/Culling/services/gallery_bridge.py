import io
import os
import uuid
import logging
from django.db import transaction
from django.core.files.base import ContentFile
from rest_framework.exceptions import ValidationError
from App.Storage.storage_models import Gallery, GallerySection, Media as GalleryMedia
from App.Photographers.photo_models import PhotographerProfile
from App.Culling.culling_models import CullingSession
from App.Culling.services.culler import purge_culling_staging
from App.Storage.services.storage_service import get_storage_provider
from App.Storage.services.media_transfer import transfer_media_to_gallery


logger = logging.getLogger(__name__)


@transaction.atomic
def move_culled_photos_to_gallery(
    user,
    session: CullingSession,
    target_mode: str = 'new',
    target_gallery_id: str = None,
    new_gallery_title: str = None,
    category_assignments: dict = None,
    include_duplicates: bool = True,
    items_payload: list = None
):
    """
    Transfers culled photos to GalleryMedia and then completely purges staging files.
    Ensures files and thumbnails are properly uploaded to storage provider before staging purge.
    """
    if not session.is_paid:
        raise ValidationError("This session must be paid before photos can be moved to a gallery.")

    # 1. Resolve Target Gallery
    photographer_profile, _ = PhotographerProfile.objects.get_or_create(
        user=user,
        defaults={'name': getattr(user, 'fullname', '') or user.username}
    )

    if target_mode == 'new':
        gallery = Gallery.objects.create(
            photographer=photographer_profile,
            title=new_gallery_title or 'AI Curated Shoot',
            status='active'
        )
    else:
        try:
            gallery = Gallery.objects.get(id=target_gallery_id, photographer=photographer_profile)
        except (Gallery.DoesNotExist, ValueError):
            try:
                gallery = Gallery.objects.get(slug=target_gallery_id, photographer=photographer_profile)
            except Gallery.DoesNotExist:
                raise ValidationError("Target gallery not found.")

    category_assignments = category_assignments or {}

    # Cache section objects
    sections_by_title = {}

    def get_or_create_section(title_str: str):
        normalized = (title_str or 'HIGHLIGHTS').strip().upper()
        if normalized not in sections_by_title:
            section, _ = GallerySection.objects.get_or_create(
                gallery=gallery,
                title=normalized,
                defaults={'order': len(sections_by_title) + 1}
            )
            sections_by_title[normalized] = section
        return sections_by_title[normalized]

    # Query items to transfer
    items_qs = session.items.all()
    if not include_duplicates:
        items_qs = items_qs.filter(status='keep')

    moved_count = 0

    for item in items_qs:
        # Determine target section from assignment dict or default
        section_name = category_assignments.get(str(item.id)) or category_assignments.get(getattr(item, 'cluster_id', None))
        if not section_name:
            section_name = 'HIGHLIGHTS' if item.status == 'keep' else 'ALTERNATE TAKES'

        section = get_or_create_section(section_name)
        item_file = item.image or getattr(item, 'file', None)

        transfer_media_to_gallery(
            gallery=gallery,
            photographer=photographer_profile,
            section=section,
            original_filename=item.original_filename or (item_file.name if item_file else "photo.jpg"),
            file_source=item_file,
            media_type='photo',
            is_favorite=(item.is_best_pick and item.status == 'keep'),
            width=item.width or 0,
            height=item.height or 0,
        )
        moved_count += 1


    # 2. PURGE ALL STAGING DATA & FILES
    purge_culling_staging(session)

    return {
        'success': True,
        'gallery_id': str(gallery.id),
        'gallery_title': gallery.title,
        'moved_count': moved_count,
        'transferred_count': moved_count,
        'purged': True,
        'message': f"Moved {moved_count} photos to '{gallery.title}' and purged culling staging."
    }


def execute_move_to_gallery(session: CullingSession, payload: dict):
    """Backward compatibility wrapper for execute_move_to_gallery."""
    return move_culled_photos_to_gallery(
        user=session.user,
        session=session,
        target_mode=payload.get('target_mode', 'new'),
        target_gallery_id=payload.get('target_gallery_id'),
        new_gallery_title=payload.get('new_gallery_title'),
        category_assignments=payload.get('category_assignments', {}),
        include_duplicates=payload.get('include_duplicates', True),
        items_payload=payload.get('items', [])
    )

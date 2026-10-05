from celery import shared_task
from django.db import transaction
from PIL import Image
from .culling_models import CullingSession, CullingItem, CullingClusterGroup
from .services.culling_engine import (
    compute_dhash_64,
    compute_laplacian_sharpness,
    cluster_culling_items,
)


@shared_task(bind=True)
def analyze_culling_session_task(self, session_id: str, similarity_threshold: float = 88.0):
    """
    Asynchronous Celery task for AI photo culling, sharpness calculation,
    and perceptual duplicate clustering.
    """
    try:
        session = CullingSession.objects.get(id=session_id)
        session.status = 'analyzing'
        session.progress_percentage = 5
        session.progress_status_text = 'Starting AI feature extraction...'
        session.save(update_fields=['status', 'progress_percentage', 'progress_status_text'])

        items = list(session.items.all())
        total_items = len(items)

        if total_items == 0:
            session.status = 'completed'
            session.progress_percentage = 100
            session.progress_status_text = 'No photos to analyze.'
            session.save(update_fields=['status', 'progress_percentage', 'progress_status_text'])
            return {'status': 'success', 'session_id': session_id}

        # 1. Feature Extraction Phase
        for idx, item in enumerate(items):
            target_file = item.image or getattr(item, 'file', None)
            file_path = target_file.path if hasattr(target_file, 'path') else target_file
            dhash_str = compute_dhash_64(file_path)
            raw_var, norm_sharpness = compute_laplacian_sharpness(file_path)

            item.dhash_hex = dhash_str
            item.sharpness_score = raw_var

            # Populate width, height, and size_bytes if not set
            if not item.width or not item.height:
                try:
                    with Image.open(file_path) as im:
                        item.width, item.height = im.size
                except Exception:
                    pass
            if not item.size_bytes:
                try:
                    item.size_bytes = target_file.size
                except Exception:
                    pass

            item.save(update_fields=['dhash_hex', 'sharpness_score', 'width', 'height', 'size_bytes'])

            # Update progress (5% to 65%)
            progress = 5 + int(((idx + 1) / total_items) * 60)
            session.progress_percentage = progress
            session.progress_status_text = f"Analyzed sharpness: {item.original_filename} ({idx + 1}/{total_items})"
            session.save(update_fields=['progress_percentage', 'progress_status_text'])

        # 2. Clustering Phase
        session.progress_percentage = 70
        session.progress_status_text = "Clustering burst sequences and structural duplicates..."
        session.save(update_fields=['progress_percentage', 'progress_status_text'])

        cluster_groups = cluster_culling_items(items, similarity_threshold=similarity_threshold)

        with transaction.atomic():
            # Delete any previous clusters
            session.clusters.all().delete()

            total_duplicates = 0
            total_saved_bytes = 0

            for idx, c_group in enumerate(cluster_groups, start=1):
                winner = c_group[0]
                duplicates = c_group[1:]

                avg_sim = round(sum(d.similarity_with_winner for d in duplicates) / len(duplicates), 1) if duplicates else 100.0
                wasted_bytes = sum(d.file_size_bytes for d in duplicates)

                cluster_obj = CullingClusterGroup.objects.create(
                    session=session,
                    cluster_number=idx,
                    average_similarity=avg_sim,
                    best_pick_item=winner,
                    total_photos=len(c_group),
                    duplicates_count=len(duplicates),
                    wasted_bytes=wasted_bytes,
                )

                for p in c_group:
                    p.cluster = cluster_obj
                    p.save(update_fields=['cluster', 'is_best_pick', 'status', 'similarity_with_winner'])

                total_duplicates += len(duplicates)
                total_saved_bytes += wasted_bytes

            # Unique photos (not in any cluster) stay as keep
            CullingItem.objects.filter(session=session, cluster__isnull=True).update(
                is_best_pick=True, status='keep'
            )

            session.total_photos = total_items
            session.duplicate_count = total_duplicates
            session.keeper_count = total_items - total_duplicates
            session.total_saved_bytes = total_saved_bytes
            session.status = 'completed'
            session.progress_percentage = 100
            session.progress_status_text = 'AI Culling & Deduplication Complete.'
            session.save()

        return {'status': 'success', 'session_id': session_id}

    except Exception as e:
        session = CullingSession.objects.filter(id=session_id).first()
        if session:
            session.status = 'draft'
            session.progress_status_text = f"Error during analysis: {str(e)}"
            session.save(update_fields=['status', 'progress_status_text'])
        raise e

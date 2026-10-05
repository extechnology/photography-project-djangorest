import logging
import cv2
import numpy as np
import imagehash
from PIL import Image
from django.db import transaction
from App.Culling.culling_models import CullingSession, CullingClusterGroup, CullingItem

logger = logging.getLogger(__name__)


def calculate_dhash_and_sharpness(pil_img: Image.Image):
    """
    1. dHash (Difference Hash, 64-bit): perceptual visual structure.
    2. Laplacian Variance: 2D convolution for edge micro-sharpness.
    """
    # 1. dHash
    dhash = imagehash.dhash(pil_img, hash_size=8)
    dhash_hex = str(dhash)

    # 2. Laplacian Sharpness
    cv_img = cv2.cvtColor(np.array(pil_img.convert('RGB')), cv2.COLOR_RGB2GRAY)
    # Downscale for fast sharpness evaluation while preserving edge gradients
    h, w = cv_img.shape
    if max(h, w) > 1024:
        scale = 1024.0 / max(h, w)
        cv_img = cv2.resize(cv_img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    laplacian = cv2.Laplacian(cv_img, cv2.CV_64F)
    sharpness_score = float(laplacian.var())

    return dhash_hex, sharpness_score


@transaction.atomic
def process_culling_session(session: CullingSession, similarity_threshold_percent: float = 88.0):
    """
    Groups items into clusters and marks the sharpest image in each cluster as the keeper.
    """
    items = list(session.items.all())
    if not items:
        session.status = 'ready'
        session.progress_percentage = 100
        session.progress_status_text = 'No photos to cull'
        session.save()
        return

    # Delete existing clusters for this session
    session.clusters.all().delete()

    max_hamming_dist = int((100.0 - similarity_threshold_percent) / 100.0 * 64)
    visited = set()
    clusters = []

    for i, item_a in enumerate(items):
        if item_a.id in visited:
            continue

        cluster_items = [item_a]
        visited.add(item_a.id)
        if not item_a.dhash_hex:
            continue
        hash_a = imagehash.hex_to_hash(item_a.dhash_hex)

        for j, item_b in enumerate(items[i + 1:], start=i + 1):
            if item_b.id in visited or not item_b.dhash_hex:
                continue
            hash_b = imagehash.hex_to_hash(item_b.dhash_hex)
            dist = hash_a - hash_b  # Hamming distance

            if dist <= max_hamming_dist:
                cluster_items.append(item_b)
                visited.add(item_b.id)

        if len(cluster_items) > 1:
            clusters.append(cluster_items)
        else:
            # Single unique photo: auto-keep
            item_a.status = 'keep'
            item_a.is_best_pick = True
            item_a.cluster = None
            item_a.save(update_fields=['status', 'is_best_pick', 'cluster'])

    total_duplicates = 0
    total_wasted_bytes = 0

    for idx, cluster_photos in enumerate(clusters, start=1):
        # Sort by sharpness descending: highest variance = sharpest winner
        cluster_photos.sort(key=lambda p: p.sharpness_score, reverse=True)
        winner = cluster_photos[0]

        cluster_obj = CullingClusterGroup.objects.create(
            session=session,
            cluster_number=idx,
            total_photos=len(cluster_photos),
            duplicates_count=len(cluster_photos) - 1,
            wasted_bytes=sum(p.size_bytes for p in cluster_photos[1:]),
            best_pick_item=winner
        )

        for p in cluster_photos:
            p.cluster = cluster_obj
            if p.id == winner.id:
                p.status = 'keep'
                p.is_best_pick = True
                p.similarity_with_winner = 100.0
            else:
                p.status = 'discard'
                p.is_best_pick = False
                dist = imagehash.hex_to_hash(winner.dhash_hex) - imagehash.hex_to_hash(p.dhash_hex)
                p.similarity_with_winner = round((1 - dist / 64.0) * 100, 1)
                total_duplicates += 1
                total_wasted_bytes += p.size_bytes

            p.save(update_fields=['cluster', 'status', 'is_best_pick', 'similarity_with_winner'])

    session.total_photos = len(items)
    session.duplicate_count = total_duplicates
    session.keeper_count = len(items) - total_duplicates
    session.total_saved_bytes = total_wasted_bytes
    session.status = 'ready'
    session.progress_percentage = 100
    session.progress_status_text = 'AI Culling Complete'
    session.save()


def purge_culling_staging(session: CullingSession):
    """
    CRITICAL CLEANUP:
    Permanently deletes all staging photos, thumbnails, and culling database rows.
    Must be called after photos are successfully moved to the target gallery.
    """
    items = list(session.items.all())
    for item in items:
        try:
            target_img = item.image or getattr(item, 'file', None)
            if target_img:
                target_img.delete(save=False)
            if item.thumbnail:
                item.thumbnail.delete(save=False)
        except Exception as e:
            logger.warning(f"Error deleting staging file: {e}")

    # Delete records from DB
    session.items.all().delete()
    session.clusters.all().delete()
    session.status = 'completed'
    session.save(update_fields=['status'])


# Backward compatibility helpers
def compute_dhash_64(image_input):
    """Takes image file-like or path, returns 64-bit binary string (or hex)."""
    if not isinstance(image_input, Image.Image):
        img = Image.open(image_input)
    else:
        img = image_input
    dhash = imagehash.dhash(img, hash_size=8)
    return ''.join(f"{int(c, 16):04b}" for c in str(dhash))


def compute_laplacian_sharpness(image_input):
    """Returns (variance, normalized_score)"""
    if not isinstance(image_input, Image.Image):
        img = Image.open(image_input)
    else:
        img = image_input
    dhash_hex, var = calculate_dhash_and_sharpness(img)
    score = min(100, max(1, int(var / 5.0)))
    return var, score


def calculate_hamming_similarity(hash_a: str, hash_b: str) -> float:
    h_a = imagehash.hex_to_hash(hash_a) if isinstance(hash_a, str) and len(hash_a) <= 16 else hash_a
    h_b = imagehash.hex_to_hash(hash_b) if isinstance(hash_b, str) and len(hash_b) <= 16 else hash_b
    if hasattr(h_a, '__sub__') and hasattr(h_b, '__sub__'):
        dist = h_a - h_b
    else:
        dist = sum(c1 != c2 for c1, c2 in zip(str(hash_a), str(hash_b)))
    return round((1 - dist / 64.0) * 100, 1)


def cluster_culling_items(items, similarity_threshold: float = 88.0):
    """Helper for testing clustering logic directly with item lists."""
    if not items:
        return []
    clusters = []
    visited = set()
    max_hamming_dist = int((100.0 - similarity_threshold) / 100.0 * 64)

    for i, itm_a in enumerate(items):
        if itm_a.id in visited:
            continue
        cluster = [itm_a]
        visited.add(itm_a.id)
        h_a = imagehash.hex_to_hash(itm_a.dhash_hex) if len(itm_a.dhash_hex) <= 16 else None

        for j, itm_b in enumerate(items[i + 1:], start=i + 1):
            if itm_b.id in visited:
                continue
            if h_a is not None and len(itm_b.dhash_hex) <= 16:
                h_b = imagehash.hex_to_hash(itm_b.dhash_hex)
                dist = h_a - h_b
            else:
                dist = sum(c1 != c2 for c1, c2 in zip(str(itm_a.dhash_hex), str(itm_b.dhash_hex)))
            if dist <= max_hamming_dist:
                cluster.append(itm_b)
                visited.add(itm_b.id)

        if len(cluster) > 1:
            cluster.sort(key=lambda x: x.sharpness_score, reverse=True)
            cluster[0].is_best_pick = True
            cluster[0].status = 'keep'
            for loser in cluster[1:]:
                loser.is_best_pick = False
                loser.status = 'discard'
            clusters.append(cluster)
        else:
            itm_a.is_best_pick = True
            itm_a.status = 'keep'

    return clusters

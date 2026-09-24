import io
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from django.conf import settings
from rest_framework import serializers

logger = logging.getLogger(__name__)

# Cached detector instance to avoid reloading ONNX graph on each request
_DETECTOR_INSTANCE = None


def get_nude_detector():
    """
    Returns a cached singleton instance of NudeDetector.
    Initializes lazily upon first request.
    """
    global _DETECTOR_INSTANCE
    if _DETECTOR_INSTANCE is None:
        try:
            from nudenet import NudeDetector
            logger.info("Initializing NudeDetector model singleton...")
            _DETECTOR_INSTANCE = NudeDetector()
            logger.info("NudeDetector initialized successfully.")
        except Exception as exc:
            logger.error(f"Failed to initialize NudeDetector: {exc}")
            raise RuntimeError(f"NudeDetector initialization failed: {exc}") from exc
    return _DETECTOR_INSTANCE


def check_image_for_nudity(
    image_input: Any,
    threshold: Optional[float] = None,
    prohibited_classes: Optional[List[str]] = None,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Inspects an image (UploadedFile, bytes, file path, or file-like object)
    using NudeNet to detect sexually explicit or nude content.

    Returns:
        (is_nude: bool, violations: list[dict])
    """
    is_enabled = getattr(settings, 'NUDE_DETECTION_ENABLED', True)
    if not is_enabled:
        return False, []

    if threshold is None:
        threshold = getattr(settings, 'NUDE_DETECTION_THRESHOLD', 0.45)

    if prohibited_classes is None:
        prohibited_classes = getattr(
            settings,
            'NUDE_DETECTION_PROHIBITED_CLASSES',
            [
                'FEMALE_GENITALIA_EXPOSED',
                'MALE_GENITALIA_EXPOSED',
                'FEMALE_BREAST_EXPOSED',
                'BUTTOCKS_EXPOSED',
                'ANUS_EXPOSED',
            ],
        )

    # 1. Extract bytes and ensure file seek position is preserved
    image_bytes = None
    if isinstance(image_input, bytes):
        image_bytes = image_input
    elif hasattr(image_input, 'read'):
        try:
            image_bytes = image_input.read()
        finally:
            if hasattr(image_input, 'seek'):
                try:
                    image_input.seek(0)
                except Exception:
                    pass
    elif isinstance(image_input, str):
        # File path
        try:
            with open(image_input, 'rb') as f:
                image_bytes = f.read()
        except Exception as e:
            logger.warning(f"Unable to read image path {image_input}: {e}")
            return False, []
    else:
        logger.warning(f"Unsupported image input type for nude detection: {type(image_input)}")
        return False, []

    if not image_bytes or len(image_bytes) == 0:
        return False, []

    # 2. Run NudeDetector
    try:
        detector = get_nude_detector()
        detections = detector.detect(image_bytes)
    except Exception as exc:
        logger.warning(f"NudeNet detection skipped (unable to process image bytes: {exc})")
        return False, []


    # 3. Filter violations against prohibited classes and threshold
    violations = []
    for item in detections:
        item_class = item.get('class')
        item_score = float(item.get('score', 0.0))
        if item_class in prohibited_classes and item_score >= threshold:
            violations.append(
                {
                    'class': item_class,
                    'score': round(item_score, 4),
                    'box': item.get('box'),
                }
            )

    return len(violations) > 0, violations


def validate_non_nude_image(image_input: Any) -> Any:
    """
    DRF/Django Field Validator that checks for explicit or nude content.
    Raises serializers.ValidationError if violation is found.
    """
    is_nude, violations = check_image_for_nudity(image_input)
    if is_nude:
        labels = {v['class'].replace('_', ' ').title() for v in violations}
        labels_str = ", ".join(sorted(labels))
        raise serializers.ValidationError(
            f"Image rejected: Inappropriate or explicit content detected ({labels_str})."
        )
    return image_input

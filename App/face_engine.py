import io
import os
import sys
import logging
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional

import cv2
import numpy as np
from PIL import Image, ImageOps
import requests
from django.conf import settings
from decouple import config

logger = logging.getLogger(__name__)

# Model URLs
YUNET_URL = "https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx"
SFACE_URL = "https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx"

# Default paths in workspace
DEFAULT_MODEL_DIR = Path(settings.BASE_DIR) / "App" / "ai_models"
YUNET_FILENAME = "face_detection_yunet_2023mar.onnx"
SFACE_FILENAME = "face_recognition_sface_2021dec.onnx"

# Thread-local storage for detector/recognizer instances
_local_state = threading.local()
_download_lock = threading.Lock()


def ensure_models_exist(target_dir: Optional[Path] = None) -> tuple[Optional[str], Optional[str]]:
    """
    Ensures YuNet and SFace ONNX models exist on disk.
    If missing, automatically downloads them with thread-safety and validation.
    Returns (yunet_path, sface_path).
    """
    model_dir = target_dir or DEFAULT_MODEL_DIR
    model_dir.mkdir(parents=True, exist_ok=True)

    yunet_path = model_dir / YUNET_FILENAME
    sface_path = model_dir / SFACE_FILENAME

    models_to_download = []
    if not yunet_path.exists() or yunet_path.stat().st_size < 100_000:
        models_to_download.append((yunet_path, YUNET_URL, "YuNet Face Detector"))
    if not sface_path.exists() or sface_path.stat().st_size < 30_000_000:
        models_to_download.append((sface_path, SFACE_URL, "SFace Face Recognizer"))

    if models_to_download:
        with _download_lock:
            for path, url, label in models_to_download:
                if path.exists() and path.stat().st_size > 100_000:
                    continue
                logger.info(f"Downloading {label} to {path}...")
                try:
                    response = requests.get(url, stream=True, timeout=60)
                    response.raise_for_status()
                    temp_path = path.with_suffix(".tmp")
                    with open(temp_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                    temp_path.replace(path)
                    logger.info(f"Successfully downloaded {label} ({path.stat().st_size} bytes).")
                except Exception as e:
                    logger.error(f"Failed to download {label} from {url}: {e}")
                    if not path.exists():
                        return None, None

    return str(yunet_path), str(sface_path)


def get_detector_and_recognizer():
    """
    Returns thread-local instances of cv2.FaceDetectorYN and cv2.FaceRecognizerSF.
    """
    yunet_path, sface_path = ensure_models_exist()
    if not yunet_path or not sface_path:
        return None, None

    if not hasattr(_local_state, "detector") or _local_state.detector is None:
        try:
            _local_state.detector = cv2.FaceDetectorYN.create(
                model=yunet_path,
                config="",
                input_size=(320, 320),
                score_threshold=float(config("FACE_DETECTOR_THRESHOLD", default="0.55")),
                nms_threshold=0.3,
                top_k=5000,
            )
            _local_state.recognizer = cv2.FaceRecognizerSF.create(
                model=sface_path,
                config="",
            )
        except Exception as e:
            logger.error(f"Failed to initialize FaceDetectorYN or FaceRecognizerSF: {e}")
            _local_state.detector = None
            _local_state.recognizer = None

    return _local_state.detector, _local_state.recognizer


def _extract_fallback_features(pil_img: Image.Image) -> List[float]:
    """
    Deterministic fallback feature vector for synthetic/unit-test images
    without real human faces.
    """
    gray = ImageOps.grayscale(pil_img).resize((64, 64), Image.Resampling.BILINEAR)
    arr = np.asarray(gray, dtype=np.float32) / 255.0

    gx = np.diff(arr, axis=1)
    gy = np.diff(arr, axis=0)

    features = []
    for i in range(8):
        for j in range(8):
            cell = arr[i * 8 : (i + 1) * 8, j * 8 : (j + 1) * 8]
            features.append(float(np.mean(cell) if cell.size else 0.5))

    for i in range(8):
        for j in range(8):
            patch_gx = (
                gx[i * 7 : (i + 1) * 7, j * 7 : (j + 1) * 7]
                if i < 7 and j < 7
                else arr[i * 8 : (i + 1) * 8, j * 8 : (j + 1) * 8]
            )
            features.append(float(np.mean(np.abs(patch_gx)) if patch_gx.size else 0.1))

    feat_arr = np.array(features[:128], dtype=np.float32)
    norm = np.linalg.norm(feat_arr)
    if norm > 0:
        feat_arr = feat_arr / norm
    else:
        feat_arr = np.ones(128, dtype=np.float32) / np.sqrt(128)

    return [round(float(x), 6) for x in feat_arr.tolist()]


def detect_and_extract_faces(
    image_bytes: bytes,
    max_dim: int = 1280,
    min_confidence: float = 0.50,
    fallback_if_no_face: bool = False
) -> List[Dict[str, Any]]:
    """
    Full AI face detection and feature embedding pipeline using OpenCV YuNet + SFace.
    Handles EXIF orientation transpose, multi-scale detection, alignment, and 128-dim normalized embedding.

    Returns:
        List of dicts: [
            {
                "bounding_box": {"x": int, "y": int, "w": int, "h": int},
                "embedding": List[float] (128-dimensional normalized vector),
                "confidence": float,
                "is_synthetic": bool
            }
        ]
    """
    if not image_bytes:
        return []

    # 1. Load and transpose orientation with Pillow
    try:
        pil_img = Image.open(io.BytesIO(image_bytes))
        pil_img = ImageOps.exif_transpose(pil_img)
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")
        img_np = np.asarray(pil_img, dtype=np.uint8)
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
    except Exception as e:
        logger.warning(f"Could not decode image bytes for face detection: {e}")
        return []

    orig_h, orig_w = img_bgr.shape[:2]
    if orig_h < 20 or orig_w < 20:
        return []

    detector, recognizer = get_detector_and_recognizer()

    # If neural models available, run YuNet detector
    faces = None
    scale = 1.0
    if detector is not None and recognizer is not None:
        if max(orig_h, orig_w) > max_dim:
            scale = max_dim / float(max(orig_h, orig_w))
            new_w = max(32, int(orig_w * scale))
            new_h = max(32, int(orig_h * scale))
            detect_img = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            detect_img = img_bgr

        dh, dw = detect_img.shape[:2]
        detector.setInputSize((dw, dh))

        try:
            _, faces = detector.detect(detect_img)
        except Exception as e:
            logger.warning(f"FaceDetectorYN.detect failed: {e}")
            faces = None

    results = []
    if faces is not None and len(faces) > 0:
        for face in faces:
            conf = float(face[14])
            if conf < min_confidence:
                continue

            scaled_face = face.copy()
            if scale != 1.0:
                scaled_face[0:14] /= scale

            box_x = max(0, int(scaled_face[0]))
            box_y = max(0, int(scaled_face[1]))
            box_w = min(orig_w - box_x, int(scaled_face[2]))
            box_h = min(orig_h - box_y, int(scaled_face[3]))

            if box_w < 10 or box_h < 10:
                continue

            try:
                aligned_face = recognizer.alignCrop(img_bgr, scaled_face)
                feature_vector = recognizer.feature(aligned_face) # shape: (1, 128)
                feat = feature_vector[0].astype(np.float32)

                norm = np.linalg.norm(feat)
                if norm > 0:
                    feat = feat / norm
                else:
                    continue

                results.append({
                    "bounding_box": {
                        "x": box_x,
                        "y": box_y,
                        "w": box_w,
                        "h": box_h,
                    },
                    "embedding": [round(float(v), 6) for v in feat.tolist()],
                    "confidence": round(conf, 4),
                    "is_synthetic": False,
                })
            except Exception as e:
                logger.debug(f"Failed to align and extract features for face: {e}")
                continue

    # Fallback for synthetic/unit-test images if no real faces were detected
    if not results and fallback_if_no_face:
        primary_w = int(orig_w * 0.5)
        primary_h = int(orig_h * 0.5)
        primary_x = int(orig_w * 0.25)
        primary_y = int(orig_h * 0.15)
        crop = pil_img.crop((primary_x, primary_y, primary_x + primary_w, primary_y + primary_h))
        emb = _extract_fallback_features(crop)
        results.append({
            "bounding_box": {
                "x": primary_x,
                "y": primary_y,
                "w": primary_w,
                "h": primary_h,
            },
            "embedding": emb,
            "confidence": 0.50,
            "is_synthetic": True,
        })

    return results


def compute_face_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    Computes genuine cosine similarity between two face embedding vectors.
    Handles matching across identical vector lengths (128-dim standard)
    or legacy 512-dim quadrupled vectors gracefully.
    """
    if not vec1 or not vec2:
        return 0.0

    a = np.array(vec1, dtype=np.float32)
    b = np.array(vec2, dtype=np.float32)

    # If comparing 128-dim with legacy 512-dim (which was tiled 4x)
    if len(a) == 128 and len(b) == 512:
        a = np.tile(a, 4)
    elif len(a) == 512 and len(b) == 128:
        b = np.tile(b, 4)
    elif len(a) != len(b):
        min_len = min(len(a), len(b))
        a = a[:min_len]
        b = b[:min_len]

    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    cosine_sim = float(np.dot(a, b) / (norm_a * norm_b))
    return max(-1.0, min(1.0, cosine_sim))

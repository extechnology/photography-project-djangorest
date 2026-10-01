import io
import os
import cv2
import numpy as np
from PIL import Image, ImageOps
from pathlib import Path
from django.test import TestCase
from django.conf import settings

from App.face_engine import (
    detect_and_extract_faces,
    compute_face_similarity,
    load_image_to_cv2,
    diagnose_face_engine,
    verify_opencv_compatibility,
    ensure_models_exist,
    get_model_dir,
    YUNET_FILENAME,
    SFACE_FILENAME,
)


class FaceEngineProductionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fixtures_dir = Path(settings.BASE_DIR) / "App" / "Storage" / "tests" / "fixtures"

        # Ensure fixtures exist
        cls.p1_path = cls.fixtures_dir / "person1_face.jpg"
        cls.selfie_path = cls.fixtures_dir / "person1_selfie.jpg"
        cls.p2_path = cls.fixtures_dir / "person2_face.jpg"
        cls.no_face_path = cls.fixtures_dir / "no_face.jpg"

    def test_opencv_compatibility_verified(self):
        """OpenCV headless package provides FaceDetectorYN and FaceRecognizerSF."""
        is_compat, msg = verify_opencv_compatibility()
        self.assertTrue(is_compat, f"OpenCV check failed: {msg}")

    def test_model_paths_and_absolute_resolution(self):
        """Model directory resolves via absolute path and contains both models."""
        model_dir = get_model_dir()
        self.assertTrue(model_dir.is_absolute(), "Model dir must be an absolute path")

        yunet_path, sface_path = ensure_models_exist()
        self.assertIsNotNone(yunet_path)
        self.assertIsNotNone(sface_path)

        self.assertTrue(os.path.exists(yunet_path))
        self.assertTrue(os.path.exists(sface_path))
        self.assertGreater(os.path.getsize(yunet_path), 100_000)
        self.assertGreater(os.path.getsize(sface_path), 30_000_000)

    def test_detect_single_face_with_accurate_embedding(self):
        """YuNet detects real face, bounds coords within image, and generates 128-dim normalized vector."""
        if not self.p1_path.exists():
            self.skipTest("Fixture person1_face.jpg not available")

        with open(self.p1_path, "rb") as f:
            data = f.read()

        results = detect_and_extract_faces(data)
        self.assertEqual(len(results), 1)

        face = results[0]
        self.assertGreaterEqual(face["confidence"], 0.50)
        self.assertFalse(face["is_synthetic"])

        bbox = face["bounding_box"]
        self.assertGreater(bbox["w"], 15)
        self.assertGreater(bbox["h"], 15)

        embedding = face["embedding"]
        self.assertEqual(len(embedding), 128)

        # Embedding must be L2 normalized (norm ~ 1.0)
        norm = np.linalg.norm(np.array(embedding, dtype=np.float32))
        self.assertAlmostEqual(norm, 1.0, places=2)

    def test_detect_no_face_image_returns_empty_no_false_positives(self):
        """Images without human faces return empty results (zero false positives)."""
        if not self.no_face_path.exists():
            self.skipTest("Fixture no_face.jpg not available")

        with open(self.no_face_path, "rb") as f:
            data = f.read()

        results = detect_and_extract_faces(data, fallback_if_no_face=False)
        self.assertEqual(len(results), 0, "Non-face image should return 0 faces")

    def test_face_recognition_same_person_high_match(self):
        """Reference gallery face and selfie of same person match with high similarity."""
        if not self.p1_path.exists() or not self.selfie_path.exists():
            self.skipTest("Fixtures not available")

        with open(self.p1_path, "rb") as f:
            r1 = detect_and_extract_faces(f.read())
        with open(self.selfie_path, "rb") as f:
            r_selfie = detect_and_extract_faces(f.read())

        self.assertEqual(len(r1), 1)
        self.assertEqual(len(r_selfie), 1)

        sim = compute_face_similarity(r1[0]["embedding"], r_selfie[0]["embedding"])
        self.assertGreater(sim, 0.80, f"Expected same-person similarity > 0.80, got {sim:.4f}")

    def test_face_recognition_different_person_distinction(self):
        """Faces of two different individuals produce low similarity (< 0.35)."""
        if not self.p1_path.exists() or not self.p2_path.exists():
            self.skipTest("Fixtures not available")

        with open(self.p1_path, "rb") as f:
            r1 = detect_and_extract_faces(f.read())
        with open(self.p2_path, "rb") as f:
            r2 = detect_and_extract_faces(f.read())

        self.assertEqual(len(r1), 1)
        self.assertEqual(len(r2), 1)

        sim = compute_face_similarity(r1[0]["embedding"], r2[0]["embedding"])
        self.assertLess(sim, 0.35, f"Expected distinct-person similarity < 0.35, got {sim:.4f}")

    def test_corrupted_or_invalid_image_bytes(self):
        """Corrupted or invalid image bytes fail gracefully without raising unhandled exceptions."""
        corrupted_bytes = b"NOT_A_VALID_IMAGE_BYTES_XYZ_1234567890"
        results = detect_and_extract_faces(corrupted_bytes)
        self.assertEqual(results, [])

        empty_results = detect_and_extract_faces(b"")
        self.assertEqual(empty_results, [])

    def test_different_image_formats_png_webp(self):
        """Detects faces accurately across PNG and WebP encoded formats."""
        if not self.p1_path.exists():
            self.skipTest("Fixture person1_face.jpg not available")

        # Load reference JPEG and re-encode to PNG and WebP
        pil_img = Image.open(self.p1_path)

        png_buf = io.BytesIO()
        pil_img.save(png_buf, format="PNG")
        png_results = detect_and_extract_faces(png_buf.getvalue())
        self.assertEqual(len(png_results), 1)

        webp_buf = io.BytesIO()
        pil_img.save(webp_buf, format="WEBP")
        webp_results = detect_and_extract_faces(webp_buf.getvalue())
        self.assertEqual(len(webp_results), 1)

        # Embeddings across JPEG, PNG, and WebP of same image should match > 0.98
        with open(self.p1_path, "rb") as f:
            jpeg_results = detect_and_extract_faces(f.read())

        sim_png = compute_face_similarity(jpeg_results[0]["embedding"], png_results[0]["embedding"])
        sim_webp = compute_face_similarity(jpeg_results[0]["embedding"], webp_results[0]["embedding"])
        self.assertGreater(sim_png, 0.98)
        self.assertGreater(sim_webp, 0.95)

    def test_large_image_scaling_and_coordinate_mapping(self):
        """Images larger than max_dim downscale for detection and map coordinates back accurately."""
        if not self.p1_path.exists():
            self.skipTest("Fixture person1_face.jpg not available")

        pil_img = Image.open(self.p1_path)
        # Upscale to 2400x2400
        large_img = pil_img.resize((2400, 2400), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        large_img.save(buf, format="JPEG", quality=90)
        large_bytes = buf.getvalue()

        results = detect_and_extract_faces(large_bytes, max_dim=1200)
        self.assertEqual(len(results), 1)

        bbox = results[0]["bounding_box"]
        # Coordinates must be within original large image bounds [0, 2400]
        self.assertGreater(bbox["x"], 0)
        self.assertLess(bbox["x"] + bbox["w"], 2400)
        self.assertGreater(bbox["y"], 0)
        self.assertLess(bbox["y"] + bbox["h"], 2400)

    def test_diagnose_face_engine_health_all_passed(self):
        """Internal diagnostic function returns HEALTHY with all checks passing."""
        diag = diagnose_face_engine()
        self.assertEqual(diag["status"], "HEALTHY")
        self.assertTrue(diag["all_passed"])
        self.assertGreaterEqual(len(diag["checks"]), 5)

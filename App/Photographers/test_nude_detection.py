import io
from unittest.mock import patch
from PIL import Image

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.exceptions import ValidationError

from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotoCategory, PhotographerProfile, PhotographerPost, PostImage
from App.Photographers.photo_serializers import PostImageSerializer, PhotographerPostSerializer
from App.Photographers.photo_utils import (
    check_image_for_nudity,
    validate_non_nude_image,
)


def create_test_image(name="test.jpg", color="green", size=(120, 120)):
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format="JPEG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/jpeg")


class NudeDetectionUnitTests(TestCase):
    def test_clean_image_not_flagged(self):
        """Clean solid-color image should not trigger any nudity violation."""
        img_file = create_test_image("clean.jpg")
        is_nude, violations = check_image_for_nudity(img_file)
        self.assertFalse(is_nude)
        self.assertEqual(violations, [])

    @patch("App.Photographers.photo_utils.get_nude_detector")
    def test_explicit_image_detected(self, mock_get_detector):
        """Image containing exposed nudity must be flagged as violation."""
        mock_detector = mock_get_detector.return_value
        mock_detector.detect.return_value = [
            {"class": "FEMALE_BREAST_EXPOSED", "score": 0.88, "box": [10, 10, 50, 50]},
            {"class": "FACE_FEMALE", "score": 0.95, "box": [0, 0, 30, 30]},
        ]

        img_file = create_test_image("explicit.jpg")
        is_nude, violations = check_image_for_nudity(img_file)

        self.assertTrue(is_nude)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["class"], "FEMALE_BREAST_EXPOSED")
        self.assertAlmostEqual(violations[0]["score"], 0.88)

    @patch("App.Photographers.photo_utils.get_nude_detector")
    def test_benign_labels_not_flagged(self, mock_get_detector):
        """Portraits, faces, or feet must not be flagged as prohibited nudity."""
        mock_detector = mock_get_detector.return_value
        mock_detector.detect.return_value = [
            {"class": "FACE_FEMALE", "score": 0.98, "box": [0, 0, 30, 30]},
            {"class": "FEET_EXPOSED", "score": 0.75, "box": [10, 10, 40, 40]},
            {"class": "ARMPITS_EXPOSED", "score": 0.60, "box": [5, 5, 20, 20]},
        ]

        img_file = create_test_image("portrait.jpg")
        is_nude, violations = check_image_for_nudity(img_file)

        self.assertFalse(is_nude)
        self.assertEqual(violations, [])

    @patch("App.Photographers.photo_utils.get_nude_detector")
    def test_low_confidence_below_threshold_ignored(self, mock_get_detector):
        """Detections below confidence threshold should be ignored."""
        mock_detector = mock_get_detector.return_value
        mock_detector.detect.return_value = [
            {"class": "BUTTOCKS_EXPOSED", "score": 0.30, "box": [10, 10, 50, 50]}
        ]

        img_file = create_test_image("low_score.jpg")
        is_nude, violations = check_image_for_nudity(img_file, threshold=0.45)

        self.assertFalse(is_nude)
        self.assertEqual(violations, [])

    def test_file_seek_preserved(self):
        """Calling check_image_for_nudity preserves file read pointer at 0."""
        img_file = create_test_image("seek_test.jpg")
        self.assertEqual(img_file.tell(), 0)

        check_image_for_nudity(img_file)
        self.assertEqual(img_file.tell(), 0)

        # Confirm data can still be read normally
        content = img_file.read()
        self.assertGreater(len(content), 0)

    @patch("App.Photographers.photo_utils.get_nude_detector")
    def test_validate_non_nude_image_raises_validation_error(self, mock_get_detector):
        """Validator should raise DRF ValidationError on detected nudity."""
        mock_detector = mock_get_detector.return_value
        mock_detector.detect.return_value = [
            {"class": "FEMALE_GENITALIA_EXPOSED", "score": 0.92, "box": [20, 20, 60, 60]}
        ]

        img_file = create_test_image("prohibited.jpg")
        with self.assertRaises(ValidationError) as ctx:
            validate_non_nude_image(img_file)

        self.assertIn("Female Genitalia Exposed", str(ctx.exception))


class NudeDetectionSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="artist_photographer",
            email="artist@test.com",
            password="password123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Fine Art Studios",
            phone="9988776655",
            email="artist@test.com",
        )
        self.category = PhotoCategory.objects.create(name="Portraits")
        self.post = PhotographerPost.objects.create(
            photographer=self.profile,
            photo_category=self.category,
            caption="Morning Light",
        )

    def test_post_image_serializer_clean_success(self):
        """PostImageSerializer accepts clean images."""
        clean_img = create_test_image("clean_art.jpg")
        serializer = PostImageSerializer(data={"post": self.post.id, "image": clean_img})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    @patch("App.Photographers.photo_utils.get_nude_detector")
    def test_post_image_serializer_nude_rejected(self, mock_get_detector):
        """PostImageSerializer rejects nude images."""
        mock_detector = mock_get_detector.return_value
        mock_detector.detect.return_value = [
            {"class": "FEMALE_BREAST_EXPOSED", "score": 0.82, "box": [10, 10, 40, 40]}
        ]

        nude_img = create_test_image("nude_art.jpg")
        serializer = PostImageSerializer(data={"post": self.post.id, "image": nude_img})
        self.assertFalse(serializer.is_valid())
        self.assertIn("image", serializer.errors)
        self.assertIn("Female Breast Exposed", str(serializer.errors["image"]))


class NudeDetectionAPIViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="studio_owner",
            email="studio@example.com",
            password="securepass123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Studio Owner",
            phone="1122334455",
            email="studio@example.com",
        )
        self.category = PhotoCategory.objects.create(name="Fashion")
        self.post = PhotographerPost.objects.create(
            photographer=self.profile,
            photo_category=self.category,
            caption="Summer Lookbook",
        )
        self.client.force_authenticate(user=self.user)

    def test_upload_clean_photo_success(self):
        """Uploading clean photos via PostImageUploadView returns 201 Created."""
        clean_photo = create_test_image("lookbook1.jpg")
        resp = self.client.post(
            f"/api/photographers/posts/{self.post.id}/images/upload/",
            {"image": clean_photo},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(PostImage.objects.filter(post=self.post).exists())

    @patch("App.Photographers.photo_utils.get_nude_detector")
    def test_upload_nude_photo_rejected(self, mock_get_detector):
        """Uploading nude photo via PostImageUploadView returns 400 Bad Request."""
        mock_detector = mock_get_detector.return_value
        mock_detector.detect.return_value = [
            {"class": "MALE_GENITALIA_EXPOSED", "score": 0.91, "box": [15, 15, 45, 45]}
        ]

        nude_photo = create_test_image("explicit_upload.jpg")
        resp = self.client.post(
            f"/api/photographers/posts/{self.post.id}/images/upload/",
            {"image": nude_photo},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("rejected_files", resp.data)
        self.assertIn("Male Genitalia Exposed", resp.data["rejected_files"][0]["reason"])

    @patch("App.Photographers.photo_utils.get_nude_detector")
    def test_create_post_with_nude_images_rejected(self, mock_get_detector):
        """Creating a post with explicit image returns 400 and does not persist."""
        mock_detector = mock_get_detector.return_value
        mock_detector.detect.return_value = [
            {"class": "BUTTOCKS_EXPOSED", "score": 0.78, "box": [10, 10, 50, 50]}
        ]

        nude_photo = create_test_image("nude_post.jpg")
        resp = self.client.post(
            "/api/photographers/posts/create/",
            {
                "photo_category": self.category.id,
                "caption": "Prohibited Content",
                "images": [nude_photo],
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("rejected_files", resp.data)
        # Verify no post with this caption was created
        self.assertFalse(PhotographerPost.objects.filter(caption="Prohibited Content").exists())

    def test_create_post_with_clean_images_success(self):
        """Creating a post with clean images successfully creates post and post images."""
        clean_photo1 = create_test_image("clean1.jpg")
        clean_photo2 = create_test_image("clean2.jpg")
        resp = self.client.post(
            "/api/photographers/posts/create/",
            {
                "photo_category": self.category.id,
                "caption": "Sunset Landscape",
                "images": [clean_photo1, clean_photo2],
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        new_post = PhotographerPost.objects.get(caption="Sunset Landscape")
        self.assertEqual(new_post.images.count(), 2)

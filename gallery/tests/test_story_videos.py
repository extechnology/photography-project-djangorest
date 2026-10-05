import io
import uuid
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from gallery.models import (
    Gallery,
    GalleryMedia,
    GalleryGuestSession,
    GalleryStoryVideo,
)
from gallery.tasks import render_story_video_ffmpeg
from App.Photographers.photo_models import PhotographerProfile

User = get_user_model()


def make_dummy_video_file(name="story.mp4") -> SimpleUploadedFile:
    content = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
    return SimpleUploadedFile(name, content, content_type="video/mp4")


class GalleryStoryVideoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='story_photographer',
            email='story@example.com',
            password='password123'
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Story Studio",
            studio_name="Cinematic Reels Studio"
        )
        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title='Grand Wedding Celebration'
        )
        self.client = APIClient()

    def test_guest_session_registration_and_update(self):
        guest_token = f"guest_tok_{uuid.uuid4().hex[:12]}"

        # 1. Missing token rejected
        res_err = self.client.post(
            f'/api/public/galleries/{self.gallery.slug}/guest-session/',
            {'name': 'Alex'},
            format='json'
        )
        self.assertEqual(res_err.status_code, status.HTTP_400_BAD_REQUEST)

        # 2. Register new guest session
        res_create = self.client.post(
            f'/api/public/galleries/{self.gallery.slug}/guest-session/',
            {
                'guest_token': guest_token,
                'name': 'Sarah & Mike',
                'email': 'sarah@example.com',
                'phone': '+919876543210'
            },
            format='json'
        )
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_create.data['name'], 'Sarah & Mike')
        self.assertEqual(res_create.data['email'], 'sarah@example.com')

        session_obj = GalleryGuestSession.objects.get(guest_token=guest_token)
        self.assertEqual(session_obj.gallery, self.gallery)

        # 3. Update existing guest session
        res_update = self.client.post(
            f'/api/public/galleries/{self.gallery.slug}/guest-session/',
            {
                'guest_token': guest_token,
                'name': 'Sarah Jenkins',
                'email': 'sarah.j@example.com'
            },
            format='json'
        )
        self.assertEqual(res_update.status_code, status.HTTP_200_OK)
        session_obj.refresh_from_db()
        self.assertEqual(session_obj.name, 'Sarah Jenkins')
        self.assertEqual(session_obj.email, 'sarah.j@example.com')

    def test_story_video_creation_and_listing(self):
        guest_token = f"guest_tok_{uuid.uuid4().hex[:12]}"
        video_file = make_dummy_video_file("reel_vertical.mp4")

        # Create story reel video
        res_create = self.client.post(
            f'/api/public/galleries/{self.gallery.slug}/story-videos/',
            {
                'guest_token': guest_token,
                'creator_name': 'Best Friends Crew',
                'title': 'The Vows Reel',
                'subtitle': 'Unforgettable Moments',
                'aspect_ratio': '9:16',
                'transition_style': 'ken-burns',
                'duration_seconds': 20.0,
                'music_title': 'A Thousand Years',
                'music_artist': 'Christina Perri',
                'photo_ids': ['p1', 'p2', 'p3'],
                'video': video_file
            },
            format='multipart'
        )
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_create.data['creator_name'], 'Best Friends Crew')
        self.assertEqual(res_create.data['aspect_ratio'], '9:16')
        self.assertEqual(res_create.data['photoCount'], 3)
        self.assertTrue(len(res_create.data['videoUrl']) > 0)

        video_id = res_create.data['id']
        story_video = GalleryStoryVideo.objects.get(id=video_id)
        self.assertEqual(story_video.gallery, self.gallery)
        self.assertIsNotNone(story_video.guest_session)
        self.assertEqual(story_video.guest_session.guest_token, guest_token)

        # List all gallery story videos
        res_list = self.client.get(f'/api/public/galleries/{self.gallery.slug}/story-videos/')
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        self.assertEqual(res_list.data['count'], 1)

        # Filter by ?guest_token=...&mine=true
        res_mine = self.client.get(
            f'/api/public/galleries/{self.gallery.slug}/story-videos/?guest_token={guest_token}&mine=true'
        )
        self.assertEqual(res_mine.status_code, status.HTTP_200_OK)
        self.assertEqual(res_mine.data['count'], 1)

        # Filter by different guest token
        res_other = self.client.get(
            f'/api/public/galleries/{self.gallery.slug}/story-videos/?guest_token=nonexistent_token&mine=true'
        )
        self.assertEqual(res_other.status_code, status.HTTP_200_OK)
        self.assertEqual(res_other.data['count'], 0)

    def test_story_video_telemetry_tracking(self):
        video_file = make_dummy_video_file("reel_telemetry.mp4")
        story_video = GalleryStoryVideo.objects.create(
            gallery=self.gallery,
            title='Telemetry Reel',
            video_file=video_file
        )

        self.assertEqual(story_video.download_count, 0)
        self.assertEqual(story_video.share_count, 0)

        # Track download
        res_dl = self.client.post(
            f'/api/public/galleries/{self.gallery.slug}/story-videos/{story_video.id}/track/',
            {'action': 'download'},
            format='json'
        )
        self.assertEqual(res_dl.status_code, status.HTTP_200_OK)
        story_video.refresh_from_db()
        self.assertEqual(story_video.download_count, 1)

        # Track share
        res_share = self.client.post(
            f'/api/public/galleries/{self.gallery.slug}/story-videos/{story_video.id}/track/',
            {'action': 'share'},
            format='json'
        )
        self.assertEqual(res_share.status_code, status.HTTP_200_OK)
        story_video.refresh_from_db()
        self.assertEqual(story_video.share_count, 1)

    def test_render_story_video_ffmpeg_task(self):
        story_video = GalleryStoryVideo.objects.create(
            gallery=self.gallery,
            title='FFmpeg Reel',
            video_file=make_dummy_video_file("task_test.mp4")
        )
        result = render_story_video_ffmpeg(story_video.id)
        self.assertIn("Rendered story video", result)

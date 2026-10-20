import os
import uuid
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

CURATED_TRACKS = [
    {
        "id": "ambient-1",
        "title": "Ethereal Reverie",
        "artist": "Atelier Ensemble",
        "genre": "Ambient & Cinematic",
        "duration": 210,
        "url": "/media/music/curated/ethereal_reverie.mp3",
        "audio_url": "/media/music/curated/ethereal_reverie.mp3",
        "is_custom": False,
    },
    {
        "id": "ambient-2",
        "title": "Golden Hour Acoustic",
        "artist": "Sundance Strings",
        "genre": "Acoustic Warmth",
        "duration": 178,
        "url": "/media/music/curated/golden_hour.mp3",
        "audio_url": "/media/music/curated/golden_hour.mp3",
        "is_custom": False,
    },
    {
        "id": "ambient-3",
        "title": "Cinematic Romance",
        "artist": "Florence Chamber Orchestra",
        "genre": "Classical Romance",
        "duration": 245,
        "url": "/media/music/curated/cinematic_romance.mp3",
        "audio_url": "/media/music/curated/cinematic_romance.mp3",
        "is_custom": False,
    },
    {
        "id": "ambient-4",
        "title": "Minimalist Piano Reverie",
        "artist": "Klara Vane",
        "genre": "Neo-Classical",
        "duration": 192,
        "url": "/media/music/curated/minimalist_piano.mp3",
        "audio_url": "/media/music/curated/minimalist_piano.mp3",
        "is_custom": False,
    },
    {
        "id": "ambient-5",
        "title": "Starlight Echoes",
        "artist": "Nordic Dawn",
        "genre": "Modern Atmospheric",
        "duration": 224,
        "url": "/media/music/curated/starlight_echoes.mp3",
        "audio_url": "/media/music/curated/starlight_echoes.mp3",
        "is_custom": False,
    },
]


class MusicTracksListView(APIView):
    """
    GET /api/music/tracks/
    Fetches curated ambient soundtrack tracks for client gallery background playback.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        base_uri = request.build_absolute_uri('/')[:-1]
        tracks = []
        for t in CURATED_TRACKS:
            item = dict(t)
            if item['url'].startswith('/'):
                item['url'] = f"{base_uri}{item['url']}"
                item['audio_url'] = item['url']
            tracks.append(item)

        return Response({
            "status": "success",
            "count": len(tracks),
            "tracks": tracks,
            "results": tracks,
        }, status=status.HTTP_200_OK)


class CustomMusicUploadView(APIView):
    """
    POST /api/music/custom/
    Uploads custom studio audio track (MP3/AAC/M4A/WAV).
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        audio_file = request.FILES.get('audio') or request.FILES.get('file') or request.FILES.get('track')
        title = request.data.get('title') or (os.path.splitext(audio_file.name)[0] if audio_file else "Custom Soundtrack")
        artist = request.data.get('artist') or getattr(request.user, 'fullname', '') or request.user.username

        if not audio_file:
            return Response(
                {"error": "No audio file provided. Please provide an 'audio' file parameter."},
                status=status.HTTP_400_BAD_REQUEST
            )

        allowed_extensions = ['.mp3', '.aac', '.m4a', '.wav', '.ogg', '.flac']
        ext = os.path.splitext(audio_file.name)[1].lower()
        if ext not in allowed_extensions:
            return Response(
                {"error": f"Invalid audio format '{ext}'. Allowed formats: {', '.join(allowed_extensions)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        track_id = f"custom_{uuid.uuid4().hex[:12]}"
        safe_filename = f"{track_id}_{audio_file.name.replace(' ', '_')}"
        save_rel_path = f"music/custom/{safe_filename}"

        saved_path = default_storage.save(save_rel_path, audio_file)
        audio_url = default_storage.url(saved_path)
        if audio_url.startswith('/'):
            audio_url = request.build_absolute_uri(audio_url)

        track_data = {
            "id": track_id,
            "title": title,
            "artist": artist,
            "url": audio_url,
            "audio_url": audio_url,
            "file_size": audio_file.size,
            "is_custom": True,
        }

        return Response({
            "status": "success",
            "message": "Custom soundtrack uploaded successfully.",
            "track": track_data,
            "data": track_data,
        }, status=status.HTTP_201_CREATED)

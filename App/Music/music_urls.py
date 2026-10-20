from django.urls import path
from .music_views import MusicTracksListView, CustomMusicUploadView

urlpatterns = [
    path('tracks/', MusicTracksListView.as_view(), name='music-tracks-list'),
    path('custom/', CustomMusicUploadView.as_view(), name='music-custom-upload'),
]

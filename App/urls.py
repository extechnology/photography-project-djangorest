from django.urls import path, include

urlpatterns = [
    path('auth/', include('App.Auth.auth_urls')),
    path('photographers/', include('App.Photographers.photo_urls')),
    path('storage/', include('App.Storage.storage_urls')),

    # Direct routes matching REST specification
    path('', include('App.Storage.storage_urls')),
]

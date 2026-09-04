from django.urls import path, include

urlpatterns = [
    path('auth/',include('App.Auth.auth_urls')),
]
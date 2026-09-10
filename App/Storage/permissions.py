from rest_framework import permissions
from App.Auth.auth_utils import get_user_from_request
from App.Photographers.photo_models import PhotographerProfile
from App.Storage.storage_models import Gallery, GalleryClientAccess


def get_authenticated_user(request):
    """Retrieves authenticated user from standard session or JWT access token."""
    if hasattr(request, "user") and request.user and request.user.is_authenticated:
        return request.user
    try:
        return get_user_from_request(request)
    except Exception:
        return None


class IsPhotographer(permissions.BasePermission):
    """Allows access only to authenticated users with a photographer profile or staff."""

    def has_permission(self, request, view):
        user = get_authenticated_user(request)
        if not user:
            return False
        if user.is_staff or user.is_superuser:
            return True
        return PhotographerProfile.objects.filter(user=user).exists()


class IsGalleryOwner(permissions.BasePermission):
    """Allows access only to the photographer who owns the gallery."""

    def has_object_permission(self, request, view, obj):
        user = get_authenticated_user(request)
        if not user:
            return False
        if user.is_staff or user.is_superuser:
            return True

        photographer = getattr(obj, "photographer", None)
        if not photographer:
            return False
        return photographer.user_id == user.id


class CanAccessGallery(permissions.BasePermission):
    """
    Checks if requester can view the gallery:
    1. Photographer owner or staff.
    2. Public gallery with valid share token.
    3. Authenticated client with a valid GalleryClientAccess record.
    4. Password-protected gallery with verified session/header.
    """

    def has_object_permission(self, request, view, obj):
        gallery = obj if isinstance(obj, Gallery) else getattr(obj, "gallery", None)
        if not gallery:
            return False

        if gallery.is_expired():
            return False

        user = get_authenticated_user(request)
        if user:
            if user.is_staff or user.is_superuser:
                return True
            if gallery.photographer.user_id == user.id:
                return True
            # Check client access invitation
            if GalleryClientAccess.objects.filter(gallery=gallery, user=user).exists():
                return True

        # Public / Share-token access
        if gallery.visibility == "public":
            return True

        if gallery.visibility == "password_protected":
            provided_pwd = request.headers.get("X-Gallery-Password") or request.query_params.get("password")
            if provided_pwd and gallery.check_access_password(provided_pwd):
                return True

        return False


class CanDownloadMedia(permissions.BasePermission):
    """Verifies that downloads are enabled on the gallery and permitted for the requester."""

    def has_object_permission(self, request, view, obj):
        gallery = obj if isinstance(obj, Gallery) else getattr(obj, "gallery", None)
        if not gallery or not gallery.downloads_enabled:
            return False

        user = get_authenticated_user(request)
        if user:
            if user.is_staff or user.is_superuser or gallery.photographer.user_id == user.id:
                return True
            access = GalleryClientAccess.objects.filter(gallery=gallery, user=user).first()
            if access:
                return access.can_download and access.is_valid()

        # Public downloads permitted if gallery allows downloads
        return gallery.visibility in ("public", "password_protected")

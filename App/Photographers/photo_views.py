import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.shortcuts import get_object_or_404, render
from django.db.models import Q, Count

from .photo_models import (
    PhotographerProfile,
    Inquiry,
)
from .photo_serializers import (
    PhotographerProfileSerializer,
    WatermarkConfigSerializer,
    WatermarkSettingsSerializer,
    OnboardingSerializer,
    OnboardingSetupSerializer,
    InquirySerializer,
)
from App.Auth.auth_models import User
from App.Auth.auth_utils import get_user_from_request
from .photo_utils import check_image_for_nudity, is_nude_detection_enabled


def check_uploaded_files_for_nudity(files):
    """Helper to check a list of uploaded files for nudity violations."""
    if not is_nude_detection_enabled():
        return []
    rejected = []
    for f in files:
        is_nude, violations = check_image_for_nudity(f)
        if is_nude:
            labels = {v['class'].replace('_', ' ').title() for v in violations}
            rejected.append({
                "filename": getattr(f, 'name', 'unnamed'),
                "reason": f"Explicit or nude content detected ({', '.join(sorted(labels))})"
            })
    return rejected



def get_current_user(request):
    if hasattr(request, 'user') and request.user and request.user.is_authenticated:
        return request.user
    try:
        return get_user_from_request(request)
    except Exception:
        return None


def get_photographer_profile(user):
    if not user:
        return None
    try:
        return getattr(user, 'photographer_profile', None) or PhotographerProfile.objects.filter(user=user).first()
    except Exception:
        return None


# =============================================================================
# Photographer Profile & Studio Suite (Frontend Contract)
# =============================================================================


class MyPhotographerProfileGetView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_or_create_profile(self, user):
        profile, created = PhotographerProfile.objects.get_or_create(
            user=user,
            defaults={
                "name": user.fullname or "",
                "email": user.email or "",
                "phone": user.phone or "",
                "studio_name": "",
                "occupation": "",
                "is_onboarded": False,
                "onboarding_step": 3,
                "default_template": "editorial",
            }
        )
        return profile

    def get(self, request):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        profile = self._get_or_create_profile(user)
        serializer = PhotographerProfileSerializer(profile, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        profile = self._get_or_create_profile(user)
        template = request.data.get('default_template')
        if template:
            active_plan = getattr(profile, 'studio_plan', None)
            if not active_plan and hasattr(profile, 'subscription') and profile.subscription and profile.subscription.plan:
                active_plan = profile.subscription.plan
            if active_plan and getattr(active_plan, 'allowed_portfolio_templates', None):
                allowed = active_plan.allowed_portfolio_templates
                alias_map = {'editorial': 'editorial-vogue', 'editorial-vogue': 'editorial-vogue', 'masonry': 'darkroom-atelier', 'darkroom-atelier': 'darkroom-atelier', 'cinematic': 'cinematic', 'minimal': 'minimal'}
                raw_t = str(template).lower().strip()
                if raw_t not in allowed and alias_map.get(raw_t, raw_t) not in [alias_map.get(str(x).lower().strip(), str(x).lower().strip()) for x in allowed]:
                    return Response(
                        {"message": f"Portfolio template '{template}' is not included in your current subscription plan."},
                        status=status.HTTP_403_FORBIDDEN
                    )

        serializer = PhotographerProfileSerializer(profile, data=request.data, context={'request': request})
        if serializer.is_valid():
            updated_profile = serializer.save()
            return Response(
                {
                    "message": "Profile updated successfully",
                    "data": PhotographerProfileSerializer(updated_profile, context={'request': request}).data
                },
                status=status.HTTP_200_OK
            )
        return Response(
            {"message": "Failed to update profile", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )

    def patch(self, request):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        profile = self._get_or_create_profile(user)
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        if 'fullname' in data and not data.get('name'):
            data['name'] = data['fullname']

        template = data.get('default_template')
        if template:
            active_plan = getattr(profile, 'studio_plan', None)
            if not active_plan and hasattr(profile, 'subscription') and profile.subscription and profile.subscription.plan:
                active_plan = profile.subscription.plan
            if active_plan and getattr(active_plan, 'allowed_portfolio_templates', None):
                allowed = active_plan.allowed_portfolio_templates
                alias_map = {'editorial': 'editorial-vogue', 'editorial-vogue': 'editorial-vogue', 'masonry': 'darkroom-atelier', 'darkroom-atelier': 'darkroom-atelier', 'cinematic': 'cinematic', 'minimal': 'minimal'}
                raw_t = str(template).lower().strip()
                if raw_t not in allowed and alias_map.get(raw_t, raw_t) not in [alias_map.get(str(x).lower().strip(), str(x).lower().strip()) for x in allowed]:
                    return Response(
                        {"message": f"Portfolio template '{template}' is not included in your current subscription plan."},
                        status=status.HTTP_403_FORBIDDEN
                    )

        serializer = PhotographerProfileSerializer(profile, data=data, partial=True, context={'request': request})
        if serializer.is_valid():
            updated_profile = serializer.save()
            return Response(
                {
                    "message": "Profile updated successfully",
                    "data": PhotographerProfileSerializer(updated_profile, context={'request': request}).data
                },
                status=status.HTTP_200_OK
            )
        return Response(
            {"message": "Failed to update profile", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class MyPhotographerAvatarUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            profile = PhotographerProfile.objects.get(user=user)
        except PhotographerProfile.DoesNotExist:
            return Response(
                {"message": "Photographer profile not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        avatar_file = request.FILES.get('avatar') or request.FILES.get('profile_image')
        if not avatar_file:
            return Response(
                {"message": "No image file provided in 'avatar' field."},
                status=status.HTTP_400_BAD_REQUEST
            )

        profile.avatar = avatar_file
        profile.profile_image = avatar_file
        profile.avatar_url = ""
        profile.save(update_fields=['avatar', 'profile_image', 'avatar_url'])

        return Response({
            "message": "Avatar uploaded successfully",
            "avatar_url": profile.get_avatar_url(),
            "data": PhotographerProfileSerializer(profile, context={'request': request}).data
        }, status=status.HTTP_200_OK)

    def delete(self, request):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            profile = PhotographerProfile.objects.get(user=user)
        except PhotographerProfile.DoesNotExist:
            return Response(
                {"message": "Photographer profile not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        if profile.avatar:
            try:
                profile.avatar.delete(save=False)
            except Exception:
                pass
            profile.avatar = None

        if profile.profile_image:
            try:
                profile.profile_image.delete(save=False)
            except Exception:
                pass
            profile.profile_image = None

        profile.avatar_url = ""
        profile.save(update_fields=['avatar', 'profile_image', 'avatar_url'])

        return Response({
            "message": "Profile photo removed successfully",
            "avatar_url": "",
            "data": PhotographerProfileSerializer(profile, context={'request': request}).data
        }, status=status.HTTP_200_OK)


class MyPhotographerWatermarkView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            profile = PhotographerProfile.objects.get(user=user)
        except PhotographerProfile.DoesNotExist:
            return Response(
                {"message": "Photographer profile not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = WatermarkSettingsSerializer(profile, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        profile = getattr(user, 'photographer_profile', None) or PhotographerProfile.objects.filter(user=user).first()
        if not profile:
            try:
                profile, _ = PhotographerProfile.objects.get_or_create(
                    user=user,
                    defaults={'name': user.get_full_name() or user.username, 'studio_name': f"{user.username} Studio"}
                )
            except Exception:
                return Response(
                    {"message": "Photographer profile not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

        serializer = WatermarkSettingsSerializer(profile, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            profile = serializer.save()
            return Response({
                "status": "success",
                "message": "Watermark configuration updated successfully.",
                "data": WatermarkSettingsSerializer(profile, context={'request': request}).data
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request):
        return self.patch(request)

    def post(self, request):
        return self.patch(request)


# Direct API alias matching specification
PhotographerWatermarkSettingsView = MyPhotographerWatermarkView


class PhotographerOnboardingView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_profile(self, user):
        profile, _ = PhotographerProfile.objects.get_or_create(
            user=user,
            defaults={
                "name": user.fullname or "",
                "email": user.email or "",
                "phone": user.phone or "",
                "is_onboarded": False,
                "onboarding_step": 3,
            }
        )
        return profile

    def get(self, request):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        profile = self.get_profile(user)
        avatar_url = ""
        if profile.avatar:
            try:
                avatar_url = request.build_absolute_uri(profile.avatar.url)
            except Exception:
                avatar_url = profile.avatar.url
        elif profile.avatar_url:
            avatar_url = profile.avatar_url

        return Response({
            "status": "success",
            "is_onboarded": profile.is_onboarded,
            "onboarding_step": profile.onboarding_step or 3,
            "name": profile.name or user.fullname or "",
            "phone": profile.phone or getattr(user, 'phone', '') or "",
            "occupation": profile.occupation or "",
            "avatar_url": avatar_url,
            "profile": PhotographerProfileSerializer(profile, context={'request': request}).data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        profile = self.get_profile(user)
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)

        # Handle alias 'fullname' -> 'name'
        if 'fullname' in data and not data.get('name'):
            data['name'] = data['fullname']

        serializer = OnboardingSerializer(profile, data=data, partial=True, context={'request': request})
        if serializer.is_valid():
            instance = serializer.save()
            instance.is_onboarded = True
            instance.onboarding_step = int(data.get('onboarding_step') or 3)

            # Custom avatar handling if uploaded or provided
            avatar_file = request.FILES.get('avatar') or request.FILES.get('profile_image')
            if avatar_file:
                instance.avatar = avatar_file
                instance.profile_image = avatar_file
                instance.avatar_url = ""
            elif data.get('avatar_url'):
                instance.avatar_url = str(data.get('avatar_url')).strip()

            instance.save()

            # Synchronize fields on User model
            user_updated_fields = []
            if hasattr(user, 'fullname') and user.fullname != instance.name:
                user.fullname = instance.name
                user_updated_fields.append('fullname')

            if hasattr(user, 'phone'):
                cleaned_phone = instance.phone.strip() or None
                if cleaned_phone and cleaned_phone != user.phone:
                    if not User.objects.filter(phone=cleaned_phone).exclude(pk=user.pk).exists():
                        user.phone = cleaned_phone
                        user_updated_fields.append('phone')

            if user_updated_fields:
                user.save(update_fields=user_updated_fields)

            avatar_url = ""
            if instance.avatar:
                try:
                    avatar_url = request.build_absolute_uri(instance.avatar.url)
                except Exception:
                    avatar_url = instance.avatar.url
            elif instance.avatar_url:
                avatar_url = instance.avatar_url

            return Response({
                "status": "success",
                "message": "Profile onboarding completed successfully",
                "is_onboarded": True,
                "onboarding_step": instance.onboarding_step,
                "profile": {
                    "id": instance.id,
                    "name": instance.name,
                    "phone": instance.phone,
                    "occupation": instance.occupation,
                    "avatar_url": avatar_url,
                    "is_onboarded": True,
                    "onboarding_step": instance.onboarding_step,
                    "storage_used_bytes": instance.storage_used_bytes,
                    "storage_limit_bytes": instance.get_storage_limit()
                },
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "fullname": instance.name,
                    "phone": instance.phone,
                    "avatar_url": avatar_url,
                    "is_onboarded": True
                }
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


OnboardingCompleteView = PhotographerOnboardingView

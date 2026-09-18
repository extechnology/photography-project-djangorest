from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.shortcuts import get_object_or_404, render
from django.db.models import Q

from .photo_models import (
    PhotoCategory,
    PhotographerProfile,
    PhotographerPost,
    PostImage,
    PostFeedback,
    Notification,
    NotificationPreference,
)
from .photo_serializers import (
    PhotoCategorySerializer,
    PhotographerProfileSerializer,
    WatermarkConfigSerializer,
    NotificationPreferenceSerializer,
    PostImageSerializer,
    PostFeedbackSerializer,
    PhotographerPostSerializer,
    NotificationSerializer,
    OnboardingSetupSerializer,
)
from App.Auth.auth_utils import get_user_from_request
from .photo_utils import check_image_for_nudity


def check_uploaded_files_for_nudity(files):
    """Helper to check a list of uploaded files for nudity violations."""
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


# =============================================================================
# 1. PhotoCategory Views (Separated GET, POST, PUT, PATCH, DELETE)
# =============================================================================

class PhotoCategoryListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        categories = PhotoCategory.objects.all()
        serializer = PhotoCategorySerializer(categories, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PhotoCategoryCreateView(APIView):
    def post(self, request):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to create a category."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        serializer = PhotoCategorySerializer(data=request.data)
        if serializer.is_valid():
            category = serializer.save()
            return Response(
                {
                    "message": "Category created successfully",
                    "data": PhotoCategorySerializer(category).data
                },
                status=status.HTTP_201_CREATED
            )
        return Response(
            {"message": "Validation failed", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class PhotoCategoryDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, pk):
        category = get_object_or_404(PhotoCategory, pk=pk)
        serializer = PhotoCategorySerializer(category)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PhotoCategoryUpdateView(APIView):
    def put(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to update a category."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        category = get_object_or_404(PhotoCategory, pk=pk)
        serializer = PhotoCategorySerializer(category, data=request.data)
        if serializer.is_valid():
            updated_category = serializer.save()
            return Response(
                {
                    "message": "Category updated successfully",
                    "data": PhotoCategorySerializer(updated_category).data
                },
                status=status.HTTP_200_OK
            )
        return Response(
            {"message": "Validation failed", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class PhotoCategoryPartialUpdateView(APIView):
    def patch(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to update a category."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        category = get_object_or_404(PhotoCategory, pk=pk)
        serializer = PhotoCategorySerializer(category, data=request.data, partial=True)
        if serializer.is_valid():
            updated_category = serializer.save()
            return Response(
                {
                    "message": "Category updated successfully",
                    "data": PhotoCategorySerializer(updated_category).data
                },
                status=status.HTTP_200_OK
            )
        return Response(
            {"message": "Validation failed", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class PhotoCategoryDeleteView(APIView):
    def delete(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to delete a category."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        category = get_object_or_404(PhotoCategory, pk=pk)
        category.delete()
        return Response(
            {"message": "Category deleted successfully"},
            status=status.HTTP_200_OK
        )


# =============================================================================
# 2. PhotographerProfile Views (Separated GET, POST, PUT, PATCH, DELETE)
# =============================================================================

class PhotographerProfileListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        profiles = PhotographerProfile.objects.select_related('user').all()
        search_query = request.query_params.get('search', None)
        if search_query:
            profiles = profiles.filter(
                Q(name__icontains=search_query) |
                Q(bio__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(phone__icontains=search_query) |
                Q(address__icontains=search_query)
            )

        serializer = PhotographerProfileSerializer(profiles, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PhotographerProfileCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to create a profile."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if PhotographerProfile.objects.filter(user=user).exists():
            return Response(
                {"message": "Photographer profile already exists for this user."},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = request.data.copy()
        if 'user' not in data:
            data['user'] = user.id

        serializer = PhotographerProfileSerializer(data=data)
        if serializer.is_valid():
            profile = serializer.save()
            return Response(
                {
                    "message": "Photographer profile created successfully",
                    "data": PhotographerProfileSerializer(profile).data
                },
                status=status.HTTP_201_CREATED
            )
        return Response(
            {"message": "Failed to create profile", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class MyPhotographerProfileGetView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_or_create_profile(self, user):
        profile, created = PhotographerProfile.objects.get_or_create(
            user=user,
            defaults={
                "name": user.fullname or user.username or "Studio Owner",
                "email": user.email or "",
                "phone": user.phone or "",
                "studio_name": "",
                "occupation": "",
                "is_onboarded": False,
                "onboarding_step": 1,
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
        serializer = PhotographerProfileSerializer(profile, data=request.data)
        if serializer.is_valid():
            updated_profile = serializer.save()
            return Response(
                {
                    "message": "Profile updated successfully",
                    "data": PhotographerProfileSerializer(updated_profile).data
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
        serializer = PhotographerProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            updated_profile = serializer.save()
            return Response(
                {
                    "message": "Profile updated successfully",
                    "data": PhotographerProfileSerializer(updated_profile).data
                },
                status=status.HTTP_200_OK
            )
        return Response(
            {"message": "Failed to update profile", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class MyPhotographerProfileUpdateView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def put(self, request):
        view = MyPhotographerProfileGetView()
        view.request = request
        view.format_kwarg = None
        return view.put(request)

    def patch(self, request):
        view = MyPhotographerProfileGetView()
        view.request = request
        view.format_kwarg = None
        return view.patch(request)


class MyPhotographerProfilePartialUpdateView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def patch(self, request):
        view = MyPhotographerProfileGetView()
        view.request = request
        view.format_kwarg = None
        return view.patch(request)


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
            "data": PhotographerProfileSerializer(profile).data
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
            "data": PhotographerProfileSerializer(profile).data
        }, status=status.HTTP_200_OK)


class ProfilePreviewView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return render(request, 'profile_preview.html')


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

        serializer = WatermarkConfigSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
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

        serializer = WatermarkConfigSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            profile = serializer.save()
            return Response({
                "message": "Watermark configuration updated successfully",
                "data": WatermarkConfigSerializer(profile).data
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class OnboardingCompleteView(APIView):
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

        return Response({
            "status": "success",
            "is_onboarded": profile.is_onboarded,
            "onboarding_step": profile.onboarding_step,
            "name": profile.name or user.fullname or "",
            "phone": profile.phone or user.phone or "",
            "occupation": profile.occupation or "",
            "location": profile.location or "",
            "studio_name": profile.studio_name,
            "avatar_url": profile.get_avatar_url(),
            "profile": PhotographerProfileSerializer(profile).data
        }, status=status.HTTP_200_OK)

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
            # Auto-create profile if missing
            profile = PhotographerProfile.objects.create(
                user=user,
                name=user.fullname or user.username or "Studio Owner",
                email=user.email or "",
                studio_name="",
                is_onboarded=False,
                onboarding_step=1
            )

        serializer = OnboardingSetupSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"status": "error", "message": "Validation failed.", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        occupation = data.get('occupation', '').strip()
        studio_name = data.get('studio_name', '').strip()
        location = data.get('location', '').strip()
        avatar_file = request.FILES.get('avatar') or request.FILES.get('profile_image')
        avatar_url = data.get('avatar_url', '').strip()

        # Update Name (Your Name)
        if name:
            profile.name = name
            user.fullname = name
            user.save(update_fields=['fullname'])

        # Update Phone Number (optional)
        if phone:
            profile.phone = phone
            if not user.phone:
                user.phone = phone
                user.save(update_fields=['phone'])

        # Update Occupation (e.g. Wedding Photographer)
        if occupation:
            profile.occupation = occupation

        # Update Studio Name / Location if provided
        if studio_name:
            profile.studio_name = studio_name
            if not profile.watermark_text or profile.watermark_text == '© Ex Studio':
                profile.watermark_text = f"© {studio_name}"

        if location:
            profile.location = location

        # Custom Profile Image (Avatar) - Optional
        if avatar_file:
            profile.avatar = avatar_file
        elif avatar_url:
            profile.avatar_url = avatar_url

        # Mark onboarding complete
        profile.is_onboarded = True
        profile.onboarding_step = int(data.get('onboarding_step') or 3)
        profile.save()

        return Response({
            "status": "success",
            "message": "Studio setup and onboarding completed successfully.",
            "is_onboarded": profile.is_onboarded,
            "onboarding_step": profile.onboarding_step,
            "profile": PhotographerProfileSerializer(profile).data,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "fullname": user.fullname,
                "phone": user.phone
            }
        }, status=status.HTTP_200_OK)


PhotographerOnboardingView = OnboardingCompleteView



class NotificationPreferenceView(APIView):
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

        prefs, _ = NotificationPreference.objects.get_or_create(photographer=profile)
        serializer = NotificationPreferenceSerializer(prefs)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request):
        return self.patch(request)

    def patch(self, request):
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

        prefs, _ = NotificationPreference.objects.get_or_create(photographer=profile)
        serializer = NotificationPreferenceSerializer(prefs, data=request.data, partial=True)
        if serializer.is_valid():
            prefs = serializer.save()
            return Response({
                "message": "Notification preferences updated successfully",
                "data": NotificationPreferenceSerializer(prefs).data
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# =============================================================================
# 3. PhotographerPost Views (Separated GET, POST, PUT, PATCH, DELETE)
# =============================================================================

class PhotographerPostListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        posts = PhotographerPost.objects.select_related(
            'photographer', 'photo_category'
        ).prefetch_related('images', 'feedbacks', 'feedbacks__user').all()

        category_id = request.query_params.get('category') or request.query_params.get('photo_category')
        if category_id:
            posts = posts.filter(photo_category_id=category_id)

        photographer_id = request.query_params.get('photographer')
        if photographer_id:
            posts = posts.filter(photographer_id=photographer_id)

        search_query = request.query_params.get('search')
        if search_query:
            posts = posts.filter(
                Q(caption__icontains=search_query) |
                Q(tech_details__icontains=search_query) |
                Q(photographer__name__icontains=search_query) |
                Q(photo_category__name__icontains=search_query)
            )

        serializer = PhotographerPostSerializer(posts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PhotographerPostCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to create a post."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        data = request.data.copy()

        # Automatically associate photographer profile if not specified
        if not data.get('photographer'):
            try:
                profile = PhotographerProfile.objects.get(user=user)
                data['photographer'] = profile.id
            except PhotographerProfile.DoesNotExist:
                return Response(
                    {"message": "User does not have a photographer profile. Please create a profile first."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        uploaded_images = request.FILES.getlist('images') or request.FILES.getlist('uploaded_images')
        if uploaded_images:
            rejected = check_uploaded_files_for_nudity(uploaded_images)
            if rejected:
                return Response(
                    {
                        "message": "Upload rejected: Explicit or nude content detected in one or more photos.",
                        "rejected_files": rejected,
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        serializer = PhotographerPostSerializer(data=data)
        if serializer.is_valid():
            post = serializer.save()


            if uploaded_images:
                for img in uploaded_images:
                    PostImage.objects.create(post=post, image=img)

            refreshed_post = PhotographerPost.objects.prefetch_related('images', 'feedbacks').get(pk=post.pk)
            return Response(
                {
                    "message": "Post created successfully",
                    "data": PhotographerPostSerializer(refreshed_post).data
                },
                status=status.HTTP_201_CREATED
            )

        return Response(
            {"message": "Failed to create post", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class PhotographerPostDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, pk):
        post = get_object_or_404(
            PhotographerPost.objects.select_related(
                'photographer', 'photo_category'
            ).prefetch_related('images', 'feedbacks', 'feedbacks__user'),
            pk=pk
        )
        serializer = PhotographerPostSerializer(post)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PhotographerPostUpdateView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def put(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to update post."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        post = get_object_or_404(PhotographerPost, pk=pk)
        if post.photographer.user != user and not (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
            return Response(
                {"message": "You do not have permission to edit this post."},
                status=status.HTTP_403_FORBIDDEN
            )

        uploaded_images = request.FILES.getlist('images') or request.FILES.getlist('uploaded_images')
        if uploaded_images:
            rejected = check_uploaded_files_for_nudity(uploaded_images)
            if rejected:
                return Response(
                    {
                        "message": "Update rejected: Explicit or nude content detected in one or more photos.",
                        "rejected_files": rejected,
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        serializer = PhotographerPostSerializer(post, data=request.data)
        if serializer.is_valid():
            updated_post = serializer.save()

            if uploaded_images:
                for img in uploaded_images:
                    PostImage.objects.create(post=updated_post, image=img)


            refreshed_post = PhotographerPost.objects.prefetch_related('images', 'feedbacks').get(pk=updated_post.pk)
            return Response(
                {
                    "message": "Post updated successfully",
                    "data": PhotographerPostSerializer(refreshed_post).data
                },
                status=status.HTTP_200_OK
            )
        return Response(
            {"message": "Failed to update post", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class PhotographerPostPartialUpdateView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def patch(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to update post."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        post = get_object_or_404(PhotographerPost, pk=pk)
        if post.photographer.user != user and not (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
            return Response(
                {"message": "You do not have permission to edit this post."},
                status=status.HTTP_403_FORBIDDEN
            )

        uploaded_images = request.FILES.getlist('images') or request.FILES.getlist('uploaded_images')
        if uploaded_images:
            rejected = check_uploaded_files_for_nudity(uploaded_images)
            if rejected:
                return Response(
                    {
                        "message": "Update rejected: Explicit or nude content detected in one or more photos.",
                        "rejected_files": rejected,
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        serializer = PhotographerPostSerializer(post, data=request.data, partial=True)
        if serializer.is_valid():
            updated_post = serializer.save()

            if uploaded_images:
                for img in uploaded_images:
                    PostImage.objects.create(post=updated_post, image=img)


            refreshed_post = PhotographerPost.objects.prefetch_related('images', 'feedbacks').get(pk=updated_post.pk)
            return Response(
                {
                    "message": "Post updated successfully",
                    "data": PhotographerPostSerializer(refreshed_post).data
                },
                status=status.HTTP_200_OK
            )
        return Response(
            {"message": "Failed to update post", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class PhotographerPostDeleteView(APIView):
    def delete(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to delete post."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        post = get_object_or_404(PhotographerPost, pk=pk)
        if post.photographer.user != user and not (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
            return Response(
                {"message": "You do not have permission to delete this post."},
                status=status.HTTP_403_FORBIDDEN
            )

        post.delete()
        return Response(
            {"message": "Post deleted successfully"},
            status=status.HTTP_200_OK
        )


class MyPhotographerPostsListView(APIView):
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

        posts = PhotographerPost.objects.filter(
            photographer=profile
        ).select_related('photo_category').prefetch_related('images', 'feedbacks')

        serializer = PhotographerPostSerializer(posts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# =============================================================================
# 4. PostImage Views (Separated GET, POST, DELETE)
# =============================================================================

class PostImageListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, post_id):
        post = get_object_or_404(PhotographerPost, pk=post_id)
        images = post.images.all()
        serializer = PostImageSerializer(images, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PostImageUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, post_id):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to upload image."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        post = get_object_or_404(PhotographerPost, pk=post_id)
        if post.photographer.user != user and not (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
            return Response(
                {"message": "You do not have permission to upload images to this post."},
                status=status.HTTP_403_FORBIDDEN
            )

        uploaded_files = request.FILES.getlist('image') or request.FILES.getlist('images')
        if uploaded_files:
            rejected = check_uploaded_files_for_nudity(uploaded_files)
            if rejected:
                return Response(
                    {
                        "message": "Upload rejected: Inappropriate or explicit content detected in one or more photos.",
                        "rejected_files": rejected,
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            created_images = []
            for file in uploaded_files:
                img_instance = PostImage.objects.create(post=post, image=file)
                created_images.append(img_instance)
            serializer = PostImageSerializer(created_images, many=True)
            return Response(
                {
                    "message": "Images uploaded successfully",
                    "data": serializer.data
                },
                status=status.HTTP_201_CREATED
            )


        data = request.data.copy()
        data['post'] = post.id
        serializer = PostImageSerializer(data=data)
        if serializer.is_valid():
            img_instance = serializer.save()
            return Response(
                {
                    "message": "Image uploaded successfully",
                    "data": PostImageSerializer(img_instance).data
                },
                status=status.HTTP_201_CREATED
            )

        return Response(
            {"message": "Image upload failed", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class PostImageDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, pk):
        image = get_object_or_404(PostImage.objects.select_related('post', 'post__photographer'), pk=pk)
        serializer = PostImageSerializer(image)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PostImageDeleteView(APIView):
    def delete(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to delete image."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        image = get_object_or_404(PostImage.objects.select_related('post', 'post__photographer'), pk=pk)
        if image.post.photographer.user != user and not (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
            return Response(
                {"message": "You do not have permission to delete this image."},
                status=status.HTTP_403_FORBIDDEN
            )

        image.delete()
        return Response(
            {"message": "Image deleted successfully"},
            status=status.HTTP_200_OK
        )


# =============================================================================
# 5. PostFeedback Views (Separated GET, POST, PUT, PATCH, DELETE)
# =============================================================================

class PostFeedbackListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, post_id):
        post = get_object_or_404(PhotographerPost, pk=post_id)
        feedbacks = post.feedbacks.select_related('user').all()
        serializer = PostFeedbackSerializer(feedbacks, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PostFeedbackCreateView(APIView):
    def post(self, request, post_id):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to submit feedback."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        post = get_object_or_404(
            PhotographerPost.objects.select_related('photographer', 'photographer__user'),
            pk=post_id
        )
        data = request.data.copy()
        data['post'] = post.id
        data['user'] = user.id

        serializer = PostFeedbackSerializer(data=data)
        if serializer.is_valid():
            feedback = serializer.save()

            # Create notification for the photographer who owns the post
            photographer_user = getattr(post.photographer, 'user', None)
            if photographer_user and photographer_user != user:
                sender_name = getattr(user, 'username', None) or getattr(user, 'email', None) or 'Someone'
                feedback_snippet = (feedback.feedback[:50] + '...') if len(feedback.feedback) > 50 else feedback.feedback
                Notification.objects.create(
                    user=photographer_user,
                    title="New Feedback on Your Post",
                    message=f"{sender_name} left a feedback on your post: \"{feedback_snippet}\""
                )

            return Response(
                {
                    "message": "Feedback submitted successfully",
                    "data": PostFeedbackSerializer(feedback).data
                },
                status=status.HTTP_201_CREATED
            )

        return Response(
            {"message": "Failed to submit feedback", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )



class PostFeedbackDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, pk):
        feedback = get_object_or_404(PostFeedback.objects.select_related('user', 'post'), pk=pk)
        serializer = PostFeedbackSerializer(feedback)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PostFeedbackUpdateView(APIView):
    def put(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to update feedback."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        feedback = get_object_or_404(PostFeedback.objects.select_related('user'), pk=pk)
        if feedback.user != user and not (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
            return Response(
                {"message": "You do not have permission to edit this feedback."},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = PostFeedbackSerializer(feedback, data=request.data)
        if serializer.is_valid():
            updated_feedback = serializer.save()
            return Response(
                {
                    "message": "Feedback updated successfully",
                    "data": PostFeedbackSerializer(updated_feedback).data
                },
                status=status.HTTP_200_OK
            )
        return Response(
            {"message": "Failed to update feedback", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class PostFeedbackPartialUpdateView(APIView):
    def patch(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to update feedback."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        feedback = get_object_or_404(PostFeedback.objects.select_related('user'), pk=pk)
        if feedback.user != user and not (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
            return Response(
                {"message": "You do not have permission to edit this feedback."},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = PostFeedbackSerializer(feedback, data=request.data, partial=True)
        if serializer.is_valid():
            updated_feedback = serializer.save()
            return Response(
                {
                    "message": "Feedback updated successfully",
                    "data": PostFeedbackSerializer(updated_feedback).data
                },
                status=status.HTTP_200_OK
            )
        return Response(
            {"message": "Failed to update feedback", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class PostFeedbackDeleteView(APIView):
    def delete(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required to delete feedback."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        feedback = get_object_or_404(PostFeedback.objects.select_related('user'), pk=pk)
        if feedback.user != user and not (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
            return Response(
                {"message": "You do not have permission to delete this feedback."},
                status=status.HTTP_403_FORBIDDEN
            )

        feedback.delete()
        return Response(
            {"message": "Feedback deleted successfully"},
            status=status.HTTP_200_OK
        )


# =============================================================================
# 6. Notification Views (Separated GET, POST, PATCH, DELETE)
# =============================================================================

class NotificationListView(APIView):
    def get(self, request):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        profile = getattr(user, 'photographer_profile', None)
        query = Q(user=user)
        if profile:
            query = query | Q(photographer=profile)

        notifications = Notification.objects.filter(query).order_by('-created_at')
        serializer = NotificationSerializer(notifications, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NotificationDetailView(APIView):
    def get(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        notification = get_object_or_404(Notification, pk=pk, user=user)
        serializer = NotificationSerializer(notification)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NotificationMarkAsReadView(APIView):
    def patch(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        notification = get_object_or_404(Notification, pk=pk, user=user)
        notification.is_read = True
        notification.save()
        return Response(
            {
                "message": "Notification marked as read",
                "data": NotificationSerializer(notification).data
            },
            status=status.HTTP_200_OK
        )


class NotificationMarkAllAsReadView(APIView):
    def post(self, request):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        updated_count = Notification.objects.filter(user=user, is_read=False).update(is_read=True)
        return Response(
            {"message": f"{updated_count} notifications marked as read"},
            status=status.HTTP_200_OK
        )


class NotificationDeleteView(APIView):
    def delete(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response(
                {"message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        notification = get_object_or_404(Notification, pk=pk, user=user)
        notification.delete()
        return Response(
            {"message": "Notification deleted successfully"},
            status=status.HTTP_200_OK
        )

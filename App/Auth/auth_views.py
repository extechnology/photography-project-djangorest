import re
import random

from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db.models import Q
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from django.conf import settings

from .auth_models import *
from .auth_serializers import *
from .auth_emails import *
from .auth_throttling import LoginRateThrottle

User = get_user_model()


def set_auth_cookies(response, refresh):
    secure = getattr(settings, 'SIMPLE_JWT_COOKIE_SECURE', False)
    samesite = getattr(settings, 'SIMPLE_JWT_COOKIE_SAMESITE', 'Lax')
    httponly = getattr(settings, 'SIMPLE_JWT_COOKIE_HTTPONLY', True)
    
    response.set_cookie(
        "access_token",
        str(refresh.access_token),
        httponly=httponly,
        secure=secure,
        samesite=samesite,
        max_age=360000
    )
    response.set_cookie(
        "refresh_token",
        str(refresh),
        httponly=httponly,
        secure=secure,
        samesite=samesite,
        max_age=7 * 24 * 360000
    )

def set_access_cookie(response, access_token):
    secure = getattr(settings, 'SIMPLE_JWT_COOKIE_SECURE', False)
    samesite = getattr(settings, 'SIMPLE_JWT_COOKIE_SAMESITE', 'Lax')
    httponly = getattr(settings, 'SIMPLE_JWT_COOKIE_HTTPONLY', True)
    
    response.set_cookie(
        "access_token",
        str(access_token),
        httponly=httponly,
        secure=secure,
        samesite=samesite,
        max_age=360000
    )

def delete_auth_cookies(response):
    samesite = getattr(settings, 'SIMPLE_JWT_COOKIE_SAMESITE', 'Lax')
    
    response.delete_cookie("access_token", samesite=samesite)
    response.delete_cookie("refresh_token", samesite=samesite)


class CheckUsernameView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def get(self, request):
        new_username = request.query_params.get("username", "").strip()

        if not new_username:
            return Response({
                "message": "Enter a username",
                "is_available": False,
                "color": "gray"
            })

        if not re.match(r'^[A-Za-z0-9_.]+$', new_username):
            return Response({
                "message": "Only letters, numbers, underscores and periods are allowed",
                "is_available": False,
                "color": "red"
            })

        if len(new_username) < 3 or len(new_username) > 20:
            return Response({
                "message": "Username must be 3 - 20 characters long",
                "is_available": False,
                "color": "red"
            })

        username_taken = User.objects.filter(username__iexact=new_username).exists()

        if username_taken:
            data = {
                "message": "Username already taken",
                "is_available": False,
                "color": "red"
            }
        else:
            data = {
                "message": "Username available",
                "is_available": True,
                "color": "green"
            }

        return Response(data)



class LogoutView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):

        response = Response({
            "message": "Logged out successfully"
        }, status=status.HTTP_200_OK)

        delete_auth_cookies(response)
        return response



class RefreshTokenView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):
        refresh_token = request.COOKIES.get("refresh_token")

        if not refresh_token:
            raise AuthenticationFailed("Authentication credentials were not provided")

        try:
            refresh = RefreshToken(refresh_token)
            new_access_token = str(refresh.access_token)
        except Exception:
            raise AuthenticationFailed("Invalid refresh token")

        response = Response({
            "message": "Access token refreshed",
        }, status=status.HTTP_200_OK)
        set_access_cookie(response, new_access_token)
        return response


class CheckLoginView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        user = request.user
        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            auth_header = request.headers.get('Authorization')
            raw_token = None
            if auth_header and auth_header.startswith('Bearer '):
                raw_token = auth_header.split(' ')[1]
            if not raw_token:
                raw_token = request.COOKIES.get('access_token')

            if raw_token:
                try:
                    token = AccessToken(raw_token)
                    user = User.objects.select_related('photographer_profile').get(id=token['user_id'])
                except Exception:
                    user = None

        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            return Response({
                'is_logged_in': False,
                'is_authenticated': False,
                'user': None,
                'message': 'No active session or access token found'
            }, status=status.HTTP_200_OK)

        profile = getattr(user, 'photographer_profile', None)
        avatar_url = None
        occupation = ""
        is_onboarded = False
        phone = getattr(user, 'phone', None) or ""
        fullname = getattr(user, 'fullname', None) or ""
        if profile:
            raw_avatar = profile.get_avatar_url()
            if raw_avatar:
                avatar_url = request.build_absolute_uri(raw_avatar) if request else raw_avatar
            occupation = profile.occupation or ""
            is_onboarded = bool(profile.is_onboarded)
            phone = profile.phone or phone
            fullname = profile.name or fullname

        user_data = {
            'id': user.id,
            'unique_id': str(user.unique_id),
            'username': user.username,
            'email': user.email,
            'fullname': fullname,
            'phone': phone,
            'occupation': occupation,
            'avatar_url': avatar_url,
            'is_onboarded': is_onboarded,
            'role': getattr(user, 'role', 'photographer'),
        }

        return Response({
            'is_logged_in': True,
            'is_authenticated': True,
            'user_id': user.id,
            'username': user.username,
            'role': getattr(user, 'role', 'photographer'),
            'user': user_data
        }, status=status.HTTP_200_OK)

        





class PasswordlessSendOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = PasswordlessSendOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "status": "error",
                    "message": "Invalid email address.",
                    "errors": serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        email = serializer.validated_data["email"]
        is_existing = User.objects.filter(email__iexact=email).exists()

        if not is_existing:
            from django.conf import settings
            max_users = getattr(settings, 'MAX_TEST_USERS', 5)
            if User.objects.filter(is_superuser=False).count() >= max_users:
                return Response(
                    {
                        "status": "error",
                        "code": "USER_LIMIT_REACHED",
                        "message": f"Registration limit reached. Only {max_users} test accounts are allowed (excluding superusers)."
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

        otp = str(random.randint(100000, 999999))
        PasswordlessLoginOTP.objects.create(email=email, otp=otp)
        send_passwordless_otp_email.delay(email, otp, is_existing_user=is_existing)

        action_label = "login" if is_existing else "registration"
        return Response(
            {
                "status": "success",
                "message": f"Verification code sent to your email for {action_label}.",
                "email": email,
                "is_registered": is_existing
            },
            status=status.HTTP_200_OK
        )


class PasswordlessResendOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = PasswordlessSendOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "status": "error",
                    "message": "Invalid email address.",
                    "errors": serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        email = serializer.validated_data["email"]
        is_existing = User.objects.filter(email__iexact=email).exists()

        otp = str(random.randint(100000, 999999))
        PasswordlessLoginOTP.objects.create(email=email, otp=otp)
        send_passwordless_otp_email.delay(email, otp, is_existing_user=is_existing)

        return Response(
            {
                "status": "success",
                "message": "A new verification code has been sent to your email.",
                "email": email,
                "is_registered": is_existing
            },
            status=status.HTTP_200_OK
        )


class PasswordlessVerifyOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = PasswordlessVerifyOTPSerializer(data=request.data)
        if not serializer.is_valid():
            err_msg = "Validation error"
            for k, v in serializer.errors.items():
                err_msg = v[0] if isinstance(v, list) and len(v) > 0 else str(v)
                break
            return Response({"status": "error", "message": err_msg}, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data["email"]
        input_otp = serializer.validated_data["otp"]
        fullname = serializer.validated_data.get("fullname", "").strip()
        role = serializer.validated_data.get("role", User.Role.PHOTOGRAPHER)

        try:
            otp_record = PasswordlessLoginOTP.objects.filter(email__iexact=email).latest("created_at")
        except PasswordlessLoginOTP.DoesNotExist:
            return Response(
                {"status": "error", "message": "No verification code found for this email. Please request a new code."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not otp_record.is_valid(input_otp):
            return Response(
                {"status": "error", "message": "Invalid or expired verification code."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Mark OTP as verified
        otp_record.is_verified = True
        otp_record.save(update_fields=["is_verified"])

        # Check if user already exists
        user = User.objects.filter(email__iexact=email).first()
        is_new_user = False

        if user:
            # Existing user -> Log in
            user.is_email_verified = True
            user.last_login = timezone.now()
            if fullname and not user.fullname:
                user.fullname = fullname
            user.save()
        else:
            from django.conf import settings
            max_users = getattr(settings, 'MAX_TEST_USERS', 5)
            if User.objects.filter(is_superuser=False).count() >= max_users:
                return Response(
                    {
                        "status": "error",
                        "code": "USER_LIMIT_REACHED",
                        "message": f"Registration limit reached. Only {max_users} test accounts are allowed (excluding superusers)."
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

            # New user -> Auto-Register without password
            is_new_user = True
            raw_base = email.split("@")[0].lower()
            base_username = re.sub(r'[^a-zA-Z0-9_.]', '', raw_base) or "user"
            candidate = base_username
            counter = 1
            while User.objects.filter(username__iexact=candidate).exists():
                candidate = f"{base_username}_{counter}"
                counter += 1

            user_fullname = fullname or ""
            user = User(
                username=candidate,
                email=email,
                role=role,
                fullname=user_fullname,
                is_email_verified=True,
                is_active=True,
                last_login=timezone.now()
            )
            user.set_unusable_password()
            user.save()

        # If user is a photographer, ensure PhotographerProfile exists
        profile = getattr(user, 'photographer_profile', None)
        if user.role == User.Role.PHOTOGRAPHER:
            from App.Photographers.photo_models import PhotographerProfile, NotificationPreference

            profile, _ = PhotographerProfile.objects.get_or_create(
                user=user,
                defaults={
                    "name": user.fullname or "",
                    "studio_name": "",
                    "location": "",
                    "email": user.email or "",
                    "is_onboarded": False,
                    "onboarding_step": 3,
                    "default_template": "editorial",
                }
            )
            NotificationPreference.objects.get_or_create(photographer=profile)

        # Issue JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        avatar_url = None
        occupation = ""
        is_onboarded = False
        phone = getattr(user, 'phone', None) or ""
        fullname_val = user.fullname or ""
        if profile:
            raw_avatar = profile.get_avatar_url()
            if raw_avatar:
                avatar_url = request.build_absolute_uri(raw_avatar) if request else raw_avatar
            occupation = profile.occupation or ""
            is_onboarded = bool(profile.is_onboarded)
            phone = profile.phone or phone
            fullname_val = user.fullname or profile.name or ""

        response_data = {
            "status": "success",
            "message": "OTP verified successfully",
            "is_new_user": is_new_user,
            "user": {
                "id": user.id,
                "unique_id": str(user.unique_id),
                "username": user.username,
                "email": user.email,
                "fullname": fullname_val,
                "phone": phone,
                "occupation": occupation,
                "avatar_url": avatar_url,
                "is_onboarded": is_onboarded,
                "role": user.role,
                "is_email_verified": user.is_email_verified
            }
        }

        response = Response(response_data, status=status.HTTP_200_OK)
        set_auth_cookies(response, refresh)
        return response



class PasswordlessLoginSendOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = PasswordlessSendOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "status": "error",
                    "message": "Invalid email address.",
                    "errors": serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        email = serializer.validated_data["email"]
        is_existing = User.objects.filter(email__iexact=email).exists()

        if not is_existing:
            return Response(
                {
                    "status": "error",
                    "message": "No account found with this email address.",
                },
                status=status.HTTP_404_NOT_FOUND
            )

        otp = str(random.randint(100000, 999999))
        PasswordlessLoginOTP.objects.create(email=email, otp=otp)
        send_passwordless_otp_email.delay(email, otp, is_existing_user=is_existing)

        action_label = "login" if is_existing else "registration"
        return Response(
            {
                "status": "success",
                "message": f"Verification code sent to your email for {action_label}.",
                "email": email,
                "is_registered": is_existing
            },
            status=status.HTTP_200_OK
        )


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):
        identifier = request.data.get("identifier")
        password = request.data.get("password")


        if not identifier or not password:
            return Response(
                {"message": "Identifier and password are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects.filter(
            Q(username=identifier) | Q(email=identifier) | Q(phone=identifier)
        ).first()

        if not user or not user.check_password(password):
            return Response(
                {"message": "Invalid credentials"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        print(user.username)

        response = Response({
            "message": "Login successful",
        }, status=status.HTTP_200_OK)

        # Set cookies
        set_auth_cookies(response, refresh)
        return response
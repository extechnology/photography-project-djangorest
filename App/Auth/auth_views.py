from django.shortcuts import render
from django.http import HttpResponse

from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.models import AnonymousUser
from django.db.models import Q

import platform
import datetime
import urllib.parse
import re
import random


from .auth_models import *

from .auth_serializers import *
from .auth_emails import *

User = get_user_model()

from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .auth_utils import get_user_from_request

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from django.conf import settings

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

class CheckIdentifierView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def get(self, request):
        identifier = request.query_params.get("identifier", "").strip()
        
        if not identifier:
            return Response({
                "message": "Enter an email address or phone number",
                "is_available": False,
            })

        is_email = re.match(r"[^@]+@[^@]+\.[^@]+", identifier)
        is_phone = re.match(r"^\+?\d{7,15}$", identifier)  # allows optional + and 7–15 digits

        if not (is_email or is_phone):
            return Response({
                "message": "Invalid email or phone number format",
                "is_available": False,
            })

        if is_email:
            exists = User.objects.filter(email__iexact=identifier).exists()
            id_type = "Email"
        else:
            exists = User.objects.filter(username__iexact=identifier).exists()  # assuming phone is stored in username
            id_type = "Phone number"

        if exists:
            data = {
                "message": f"{id_type} already exists",
                "is_available": False,
            }
        else:
            data = {
                "message": f"{id_type} is available",
                "is_available": True,
            }

        return Response(data)


# @rate_limit(key='ip', rate='1/m', block=True)
class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):               
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "One time password sent to your email/phone for verification"}, status=status.HTTP_201_CREATED)
        return Response({
            'message': 'Registration failed',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

# @rate_limit(key='ip', rate='1/m', block=True)
class ResendOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):
       serializer = ResentOTPSerializer(data=request.data, context={'request': request})
       if serializer.is_valid():
           serializer.save()
           return Response({"message": "One time password sent to your email/phone for verification"}, status=status.HTTP_201_CREATED)
       return Response({
           'message': 'Registration failed',
           'errors': serializer.errors
         }, status=status.HTTP_400_BAD_REQUEST)
   
   
class VerifyOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request,):
        serializer = EmailOTPVerifySerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()  # capture the created user here
            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)

            response = Response({
                'message': 'Account verified successfully',
            }, status=status.HTTP_200_OK)

            set_auth_cookies(response, refresh)
            return response
        # --- flatten the error response here ---
        errors = serializer.errors
        message = None

        if isinstance(errors, dict):
            # Try to get first field error
            for key, value in errors.items():
                if isinstance(value, list) and len(value) > 0:
                    message = value[0]
                else:
                    message = value
                break
        elif isinstance(errors, list):
            message = errors[0]
        else:
            message = str(errors)

        return Response({"message": message}, status=status.HTTP_400_BAD_REQUEST)




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
                    user = User.objects.get(id=token['user_id'])
                except Exception:
                    user = None

        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            return Response({
                'is_logged_in': False,
                'is_authenticated': False,
                'user': None,
                'message': 'No active session or access token found'
            }, status=status.HTTP_200_OK)

        user_data = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'phone': getattr(user, 'phone', None),
            'role': getattr(user, 'role', 'photographer'),
            'fullname': getattr(user, 'fullname', user.username),
        }

        return Response({
            'is_logged_in': True,
            'is_authenticated': True,
            'user_id': user.id,
            'username': user.username,
            'role': getattr(user, 'role', 'photographer'),
            'user': user_data
        }, status=status.HTTP_200_OK)

        



class DirectResetPasswordView(APIView):
    def post(self, request):
        user = request.user
        password = request.data.get("password") 
        current_password = request.data.get("current_password")
        
        if current_password is None:
            return Response(
                {"error": "Current password is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not user.check_password(current_password):
            return Response(
                {"error": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not password:
            return Response(
                {"error": "Password is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user.set_password(password)
            user.save()
            password_reset_success_email(user, user.email, password)
            return Response({"message": "Password reset successfully."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": "Password reset failed."},
                status=status.HTTP_400_BAD_REQUEST
            )   

class ResetPasswordOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            response = Response({
                'message': 'OTP sent successfully',
            }, status=status.HTTP_200_OK)

            return response
        
            errors = serializer.errors
            message = None
    
            if isinstance(errors, dict):
                # Try to get first field error
                for key, value in errors.items():
                    if isinstance(value, list) and len(value) > 0:
                        message = value[0]
                    else:
                        message = value
                    break
            elif isinstance(errors, list):
                message = errors[0]
            else:
                message = str(errors)

        return Response({"message": message}, status=status.HTTP_400_BAD_REQUEST)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ResendResetPasswordOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):
        serializer = ResendResetPasswordOTPSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "One time password sent to your email/phone for verification."}, status=status.HTTP_201_CREATED)
            errors = serializer.errors
            message = None
    
            if isinstance(errors, dict):
                # Try to get first field error
                for key, value in errors.items():
                    if isinstance(value, list) and len(value) > 0:
                        message = value[0]
                    else:
                        message = value
                    break
            elif isinstance(errors, list):
                message = errors[0]
            else:
                message = str(errors)
        return Response({
            'message': 'Registration failed',
            'errors': serializer.errors
          }, status=status.HTTP_400_BAD_REQUEST)
        

class VerifyResetPasswordOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):
        serializer = VerifyResetPasswordSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "OTP verified successfully"}, status=status.HTTP_200_OK)
        else:
            errors = serializer.errors
            message = None

            if isinstance(errors, dict):
                for key, value in errors.items():
                    if isinstance(value, list) and len(value) > 0:
                        message = value[0]
                    else:
                        message = value
                    break
            elif isinstance(errors, list):
                message = errors[0]
            else:
                message = str(errors)

            return Response({"message": message}, status=status.HTTP_400_BAD_REQUEST)


class ChangePasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def patch(self, request):
        identifier = request.data.get("identifier")
        new_password = request.data.get("new_password")
        
        if ResetPasswordOTP.objects.filter(identifier=identifier, is_verified=True).exists():
            try:
                user = User.objects.get(Q(email__iexact=identifier) | Q(phone__iexact=identifier) | Q(username__iexact=identifier))
                user.set_password(new_password)
                user.save()
                email = user.email
                password_changed_email(user, email)
                # Invalidate the OTP after use
                ResetPasswordOTP.objects.filter(identifier=identifier).delete()
                
                password_reset_success_email(user, user.email, new_password)
                
                return Response({"message": "Password reset successfully."}, status=status.HTTP_200_OK)
            except User.DoesNotExist:
                return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response({"error": "Invalid or unverified OTP."}, status=status.HTTP_400_BAD_REQUEST)
    

    
# ---------------------------------------- End of Authentication Views --------------------------------------------------------------

GOOGLE_CLIENT_ID = getattr(settings, 'GOOGLE_CLIENT_ID', None)
class GoogleAuthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):
        if not GOOGLE_CLIENT_ID:
            return Response({"message": "Google Authentication is not configured in settings.py"}, status=status.HTTP_501_NOT_IMPLEMENTED)

        token = request.data.get("token")

        if not token:
            return Response({"message": "Token is required"}, status=status.HTTP_400_BAD_REQUEST)


        try:
            # Check if it's a JWT ID Token (3 segments separated by dots)
            if token.count('.') == 2:
                idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), audience=GOOGLE_CLIENT_ID)
                if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
                    raise ValueError('Wrong issuer.')
                email = idinfo.get('email')
                fullname = idinfo.get('name')
            else:
                # Otherwise, treat it as an OAuth2 Access Token
                import requests
                userinfo_response = requests.get(
                    'https://www.googleapis.com/oauth2/v3/userinfo',
                    headers={'Authorization': f'Bearer {token}'}
                )
                if not userinfo_response.ok:
                    raise ValueError('Invalid Google Access Token.')
                
                userinfo = userinfo_response.json()
                email = userinfo.get('email')
                fullname = userinfo.get('name')

            if not email:
                raise ValueError('Email not found in Google response.')

            if not User.objects.filter(email=email).exists():
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

            user, created = User.objects.get_or_create(
                email=email, 
                defaults={'username': email.split('@')[0], 'fullname': fullname}
            )

            user.is_email_verified = True
            user.save()

            refresh = RefreshToken.for_user(user)

            response = Response({
                'message': 'Login successful',
                # 'access_token': str(refresh.access_token),
                # 'refresh_token': str(refresh)
            }, status=status.HTTP_200_OK)

            set_auth_cookies(response, refresh)
            return response

        except ValueError as e:
            return Response({"message": f"Invalid token: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)


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

            user_fullname = fullname or base_username.replace('.', ' ').replace('_', ' ').title()
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

        # If user is a photographer, ensure PhotographerProfile & subscription exist
        if user.role == User.Role.PHOTOGRAPHER:
            from datetime import timedelta
            from App.Photographers.photo_models import PhotographerProfile, NotificationPreference
            from App.Subscriptions.sub_models import SubscriptionPlans, PhotographerSubscription

            profile, _ = PhotographerProfile.objects.get_or_create(
                user=user,
                defaults={
                    "name": user.fullname or user.username,
                    "studio_name": "",
                    "location": "",
                    "email": user.email,
                    "is_onboarded": False,
                    "onboarding_step": 1,
                    "default_template": "editorial",
                }
            )
            NotificationPreference.objects.get_or_create(photographer=profile)

            # Assign default plan if not present
            if not PhotographerSubscription.objects.filter(photographer=profile).exists():
                plan = SubscriptionPlans.objects.filter(tier='pro').first() or SubscriptionPlans.objects.first()
                if plan:
                    PhotographerSubscription.objects.create(
                        photographer=profile,
                        plan=plan,
                        status='active',
                        expires_at=timezone.now() + timedelta(days=365)
                    )

        # Issue JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        response_data = {
            "status": "success",
            "message": "Account registered and logged in successfully." if is_new_user else "Login successful.",
            "is_new_user": is_new_user,

            "user": {
                "id": user.id,
                "unique_id": str(user.unique_id),
                "username": user.username,
                "email": user.email,
                "fullname": user.fullname,
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


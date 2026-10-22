from django.urls import path
from .auth_views import (
    CheckUsernameView,
    CheckLoginView,
    RefreshTokenView,
    LogoutView,
    PasswordlessSendOTPView,
    PasswordlessVerifyOTPView,
    PasswordlessResendOTPView,
    PasswordlessLoginSendOTPView,
    LoginView
)

urlpatterns = [
    # Username Availability
    path('check-username/', CheckUsernameView.as_view(), name='check-username'),

    # Session & Token Management
    path('check-login/', CheckLoginView.as_view(), name='check-login'),
    path('token/refresh/', RefreshTokenView.as_view(), name='token-refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),

    # Passwordless Authentication (Email -> OTP -> Login / Register)
    path('passwordless/reg/send-otp/', PasswordlessSendOTPView.as_view(), name='passwordless-reg-send-otp'),
    path('passwordless/reg/verify-otp/', PasswordlessVerifyOTPView.as_view(), name='passwordless-reg-verify-otp'),
    path('passwordless/reg/resend-otp/', PasswordlessResendOTPView.as_view(), name='passwordless-reg-resend-otp'),

    path('passwordless/login/send-otp/', PasswordlessLoginSendOTPView.as_view(), name='passwordless-login-send-otp'),
    path('passwordless/login/verify-otp/', PasswordlessVerifyOTPView.as_view(), name='passwordless-login-verify-otp'),
    path('passwordless/login/resend-otp/', PasswordlessResendOTPView.as_view(), name='passwordless-login-resend-otp'),

    path('login/', LoginView.as_view(), name='login'),
]


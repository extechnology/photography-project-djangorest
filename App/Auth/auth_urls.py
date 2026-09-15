from django.urls import path
from .auth_views import (
    CheckUsernameView,
    CheckIdentifierView,
    RegisterView,
    ResendOTPView,
    VerifyOTPView,
    LoginView,
    LogoutView,
    RefreshTokenView,
    CheckLoginView,
    DirectResetPasswordView,
    ResetPasswordOTPView,
    ResendResetPasswordOTPView,
    VerifyResetPasswordOTPView,
    ChangePasswordView,
    GoogleAuthView,
    PasswordlessSendOTPView,
    PasswordlessVerifyOTPView,
    PasswordlessResendOTPView,
    PasswordlessLoginSendOTPView
)

urlpatterns = [
    path('check-username/', CheckUsernameView.as_view(), name='check-username'),
    path('check-identifier/', CheckIdentifierView.as_view(), name='check-identifier'),
    path('register/', RegisterView.as_view(), name='register'),
    path('resend-otp/', ResendOTPView.as_view(), name='resend-otp'),
    path('verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('token/refresh/', RefreshTokenView.as_view(), name='token-refresh'),
    path('check-login/', CheckLoginView.as_view(), name='check-login'),
    path('reset-password/direct/', DirectResetPasswordView.as_view(), name='direct-reset-password'),
    path('reset-password/otp/', ResetPasswordOTPView.as_view(), name='reset-password-otp'),
    path('reset-password/resend-otp/', ResendResetPasswordOTPView.as_view(), name='resend-reset-password-otp'),
    path('reset-password/verify-otp/', VerifyResetPasswordOTPView.as_view(), name='verify-reset-password-otp'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('google/', GoogleAuthView.as_view(), name='google-auth'),

    # Passwordless Authentication (Email -> OTP -> Login / Register)
    path('passwordless/reg/send-otp/', PasswordlessSendOTPView.as_view(), name='passwordless-reg-send-otp'),
    path('passwordless/reg/verify-otp/', PasswordlessVerifyOTPView.as_view(), name='passwordless-reg-verify-otp'),
    path('passwordless/reg/resend-otp/', PasswordlessResendOTPView.as_view(), name='passwordless-reg-resend-otp'),

    path('passwordless/login/send-otp/', PasswordlessLoginSendOTPView.as_view(), name='passwordless-login-send-otp'),
    path('passwordless/login/verify-otp/', PasswordlessVerifyOTPView.as_view(), name='passwordless-login-verify-otp'),
    path('passwordless/login/resend-otp/', PasswordlessResendOTPView.as_view(), name='passwordless-login-resend-otp'),

]


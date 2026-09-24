import requests
import random
import logging
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from celery import shared_task

logger = logging.getLogger(__name__)

# ==============================================================================
# EMAIL DESIGN SYSTEM: EX SHARE (Black & Off-White Monochrome Theme)
# ==============================================================================

def _render_email_wrapper(header_title, headline, body_html, footer_note=None):
    """
    Renders a unified, high-contrast, luxury Black & Off-White email template.
    Uses pure inline styles for maximum compatibility across Gmail, Apple Mail, Outlook.
    """
    footer_text = footer_note if footer_note else "This is an automated notification from EX SHARE."
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EX SHARE</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #000000; color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #000000; padding: 40px 16px;">
        <tr>
            <td align="center">
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width: 540px; background-color: #111111; border: 1px solid #262626; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.8);">
                    <!-- Brand Header -->
                    <tr>
                        <td style="background-color: #080808; padding: 32px 30px; text-align: center; border-bottom: 1px solid #222222;">
                            <div style="font-size: 13px; letter-spacing: 4px; text-transform: uppercase; color: #a3a3a3; font-weight: 800; margin-bottom: 8px;">
                                EX SHARE
                            </div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 22px; font-weight: 700; letter-spacing: -0.3px;">
                                {headline}
                            </h1>
                        </td>
                    </tr>

                    <!-- Body Content -->
                    <tr>
                        <td style="padding: 36px 32px; text-align: center; color: #e5e5e5; font-size: 15px; line-height: 1.6;">
                            {body_html}
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #080808; padding: 22px 30px; border-top: 1px solid #222222; text-align: center;">
                            <p style="margin: 0 0 6px; font-size: 12px; color: #737373;">
                                {footer_text}
                            </p>
                            <p style="margin: 0; font-size: 11px; color: #525252;">
                                &copy; 2026 EX SHARE. All rights reserved.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""


# ==============================================================================
# EMAIL HANDLERS
# ==============================================================================

@shared_task
def send_registration_otp_email(identifier, otp):
    subject = "[EX SHARE] Your Verification Code"
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '')
    to = [identifier]

    text_content = (
        f"Your verification code for registration on EX SHARE is: {otp}\n\n"
        f"This code will expire in 10 minutes. Do not share it with anyone."
    )

    body_html = f"""
        <p style="margin: 0 0 20px; font-size: 15px; color: #e5e5e5;">
            Thank you for registering on <strong>EX SHARE</strong>.<br>
            Please use the one-time verification code below to complete your account setup:
        </p>

        <!-- OTP Display Box -->
        <div style="margin: 28px auto 20px; display: inline-block; padding: 18px 40px; background-color: #050505; border: 1.5px dashed #525252; border-radius: 10px; cursor: pointer; user-select: all; -webkit-user-select: all;">
            <span style="font-family: 'Courier New', Courier, monospace; font-size: 36px; font-weight: 800; letter-spacing: 10px; color: #ffffff; display: block; user-select: all; -webkit-user-select: all;">
                {otp}
            </span>
        </div>

        <p style="margin: 8px 0 0; font-size: 12px; color: #737373;">
            Tip: Tap or double-click the code above to select and copy it.
        </p>

        <p style="margin: 24px 0 0; font-size: 13px; color: #8a8a8a;">
            This OTP is valid for <strong>10 minutes</strong>. Do not share it with anyone.
        </p>
    """

    html_content = _render_email_wrapper(
        header_title="EX SHARE",
        headline="Registration Verification",
        body_html=body_html
    )

    try:
        msg = EmailMultiAlternatives(subject, text_content, from_email, to)
        msg.attach_alternative(html_content, "text/html")
        msg.send()
    except Exception as e:
        logger.warning(f"Failed to deliver registration OTP email to {identifier}: {e}. OTP: {otp}")


def user_created_email(user, email):
    subject = "Welcome to EX SHARE - Account Created"
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '')
    to = [email]

    text_content = f"Hello {user.username},\n\nWelcome to EX SHARE! Your account has been successfully created."

    body_html = f"""
        <p style="margin: 0 0 16px; font-size: 16px; color: #ffffff;">
            Hello <strong>{user.username}</strong>,
        </p>
        <p style="margin: 0 0 24px; font-size: 15px; color: #d4d4d4;">
            Welcome to <strong>EX SHARE</strong>! Your account has been successfully created. You can now log in, manage your high-resolution media galleries, and collaborate securely.
        </p>
        <div style="margin: 24px auto; padding: 16px 24px; background-color: #050505; border: 1px solid #262626; border-radius: 8px; display: inline-block;">
            <span style="font-size: 14px; color: #a3a3a3;">Username: <strong style="color: #ffffff;">{user.username}</strong></span>
        </div>
    """

    html_content = _render_email_wrapper(
        header_title="EX SHARE",
        headline="Welcome to EX SHARE",
        body_html=body_html
    )

    try:
        msg = EmailMultiAlternatives(subject, text_content, from_email, to)
        msg.attach_alternative(html_content, "text/html")
        msg.send()
    except Exception as e:
        logger.warning(f"Failed to deliver user created email to {email}: {e}")


def login_detected_email(user, email, ip_address, user_agent, login_time, notify_url_yes, notify_url_no):
    subject = "[EX SHARE] Security Alert: New Login Detected"
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '')
    to = [email]

    text_content = (
        f"Hello {user.username},\n\n"
        f"A new sign-in was detected on your EX SHARE account.\n"
        f"Time: {login_time}\n"
        f"Device: {user_agent}\n"
        f"IP Address: {ip_address}\n\n"
        f"If this was not you, please secure your account immediately."
    )

    body_html = f"""
        <p style="margin: 0 0 16px; color: #ffffff; font-size: 16px; text-align: left;">
            Hello <strong>{user.username}</strong>,
        </p>
        <p style="margin: 0 0 28px; color: #d4d4d4; font-size: 14px; line-height: 1.6; text-align: left;">
            We detected a new sign-in to your EX SHARE account. If this was you, no action is needed. If you don't recognize this activity, please reset your password immediately.
        </p>

        <!-- Login Details Table -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #050505; border: 1px solid #262626; border-radius: 8px; margin-bottom: 24px; text-align: left;">
            <tr>
                <td style="padding: 18px 20px;">
                    <div style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: #a3a3a3; margin-bottom: 12px;">
                        Session Details
                    </div>
                    <table width="100%" cellpadding="6" cellspacing="0" border="0" style="font-size: 13px;">
                        <tr>
                            <td style="color: #737373; width: 100px; padding: 6px 0;">Time</td>
                            <td style="color: #f5f5f5; padding: 6px 0;">{login_time}</td>
                        </tr>
                        <tr>
                            <td style="color: #737373; padding: 6px 0;">Device</td>
                            <td style="color: #f5f5f5; padding: 6px 0;">{user_agent}</td>
                        </tr>
                        <tr>
                            <td style="color: #737373; padding: 6px 0;">IP Address</td>
                            <td style="color: #ffffff; font-family: 'Courier New', Courier, monospace; padding: 6px 0;">{ip_address}</td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>

        <div style="padding: 14px 18px; background-color: #171717; border-left: 3px solid #737373; border-radius: 4px; text-align: left;">
            <p style="margin: 0; font-size: 12px; color: #a3a3a3; line-height: 1.5;">
                <strong style="color: #ffffff;">Security Notice:</strong> If you did not perform this login, change your password immediately to protect your media assets.
            </p>
        </div>
    """

    html_content = _render_email_wrapper(
        header_title="EX SHARE",
        headline="Security Alert",
        body_html=body_html,
        footer_note="Automated security alert from EX SHARE."
    )

    try:
        msg = EmailMultiAlternatives(subject, text_content, from_email, to)
        msg.attach_alternative(html_content, "text/html")
        msg.send()
    except Exception as e:
        logger.warning(f"Failed to deliver login notification email to {email}: {e}")


def password_reset_success_email(user, email, new_password):
    subject = "[EX SHARE] Password Reset Successfully"
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '')
    to = [email]

    text_content = (
        f"Hello {user.username},\n\n"
        f"Your EX SHARE account password has been reset successfully.\n"
        f"Your new password is: {new_password}\n\n"
        f"If you did not request this change, please contact support immediately."
    )

    body_html = f"""
        <p style="margin: 0 0 16px; font-size: 16px; color: #ffffff;">
            Hello <strong>{user.username}</strong>,
        </p>
        <p style="margin: 0 0 24px; font-size: 15px; color: #d4d4d4;">
            Your password for <strong>EX SHARE</strong> has been reset successfully.
        </p>
        <div style="margin: 20px auto; padding: 16px 28px; background-color: #050505; border: 1.5px dashed #525252; border-radius: 8px; display: inline-block; user-select: all; -webkit-user-select: all;">
            <span style="font-size: 12px; color: #737373; display: block; margin-bottom: 6px;">NEW TEMPORARY PASSWORD</span>
            <span style="font-family: 'Courier New', Courier, monospace; font-size: 22px; font-weight: 700; letter-spacing: 2px; color: #ffffff;">
                {new_password}
            </span>
        </div>
        <p style="margin: 20px 0 0; font-size: 13px; color: #8a8a8a;">
            If you did not make this change, please contact support immediately.
        </p>
    """

    html_content = _render_email_wrapper(
        header_title="EX SHARE",
        headline="Password Reset",
        body_html=body_html
    )

    try:
        msg = EmailMultiAlternatives(subject, text_content, from_email, to)
        msg.attach_alternative(html_content, "text/html")
        msg.send()
    except Exception as e:
        logger.warning(f"Failed to deliver password reset email to {email}: {e}")


def forgot_password_otp_email(identifier, otp):
    subject = "[EX SHARE] Password Reset Code"
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '')
    to = [identifier]

    text_content = (
        f"Your OTP for password reset on EX SHARE is: {otp}\n\n"
        f"This code will expire in 10 minutes. Do not share it with anyone."
    )

    body_html = f"""
        <p style="margin: 0 0 20px; font-size: 15px; color: #e5e5e5;">
            You requested a password reset on <strong>EX SHARE</strong>.<br>
            Use the verification code below to complete your password reset:
        </p>

        <!-- OTP Display Box -->
        <div style="margin: 28px auto 20px; display: inline-block; padding: 18px 40px; background-color: #050505; border: 1.5px dashed #525252; border-radius: 10px; cursor: pointer; user-select: all; -webkit-user-select: all;">
            <span style="font-family: 'Courier New', Courier, monospace; font-size: 36px; font-weight: 800; letter-spacing: 10px; color: #ffffff; display: block; user-select: all; -webkit-user-select: all;">
                {otp}
            </span>
        </div>

        <p style="margin: 8px 0 0; font-size: 12px; color: #737373;">
            Tip: Tap or double-click the code above to select and copy it.
        </p>

        <p style="margin: 24px 0 0; font-size: 13px; color: #8a8a8a;">
            This OTP is valid for <strong>10 minutes</strong>. If you did not request this, you can safely ignore this email.
        </p>
    """

    html_content = _render_email_wrapper(
        header_title="EX SHARE",
        headline="Password Reset OTP",
        body_html=body_html
    )

    try:
        msg = EmailMultiAlternatives(subject, text_content, from_email, to)
        msg.attach_alternative(html_content, "text/html")
        msg.send()
    except Exception as e:
        logger.warning(f"Failed to deliver forgot password OTP email to {identifier}: {e}")


def password_changed_email(user, email):
    subject = "[EX SHARE] Password Changed Successfully"
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '')
    to = [email]

    text_content = f"Hello {user.username},\n\nYour EX SHARE password has been changed successfully."

    body_html = f"""
        <p style="margin: 0 0 16px; font-size: 16px; color: #ffffff;">
            Hello <strong>{user.username}</strong>,
        </p>
        <p style="margin: 0 0 20px; font-size: 15px; color: #d4d4d4;">
            Your password for <strong>EX SHARE</strong> has been changed successfully.
        </p>
        <p style="margin: 0; font-size: 13px; color: #8a8a8a;">
            If you did not make this change, please contact our support team immediately to secure your account.
        </p>
    """

    html_content = _render_email_wrapper(
        header_title="EX SHARE",
        headline="Password Changed",
        body_html=body_html
    )

    try:
        msg = EmailMultiAlternatives(subject, text_content, from_email, to)
        msg.attach_alternative(html_content, "text/html")
        msg.send()
    except Exception as e:
        logger.warning(f"Failed to deliver password changed email to {email}: {e}")



@shared_task
def send_passwordless_otp_email(email, otp, is_existing_user=True):
    """
    Sends a 6-digit one-time password (OTP) for passwordless login or registration.
    Black & Off-White luxury monochrome styling.
    """
    action_text = "sign in to EX SHARE" if is_existing_user else "create your EX SHARE account"
    headline = "Your EX SHARE Access Code" if is_existing_user else "Welcome to EX SHARE"
    subject = f"{otp} is your EX SHARE verification code"

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '')
    to = [email]

    text_content = (
        f"Your verification code to {action_text} is: {otp}\n\n"
        f"This code will expire in 10 minutes. Do not share it with anyone."
    )

    body_html = f"""
        <p style="margin: 0 0 20px; font-size: 15px; color: #e5e5e5; line-height: 1.6;">
            Use the secure one-time passcode below to <strong>{action_text}</strong>.
        </p>

        <!-- OTP Box (1-tap full selection, no external redirection) -->
        <div style="margin: 28px auto 0; display: inline-block; padding: 18px 40px 14px; background-color: #050505; border: 1.5px dashed #525252; border-radius: 12px 12px 0 0; cursor: pointer; user-select: all; -webkit-user-select: all; -moz-user-select: all;">
            <span style="font-family: 'Courier New', Courier, monospace; font-size: 36px; font-weight: 800; letter-spacing: 10px; color: #ffffff; display: block; user-select: all; -webkit-user-select: all;">
                {otp}
            </span>
        </div>

        <!-- Copy affordance (visual button; selects the code on tap since email clients block JS clipboard actions) -->
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin: 0 auto 20px;">
            <tr>
                <td style="background-color: #1a1a1a; border: 1px solid #333333; border-top: none; border-radius: 0 0 12px 12px; padding: 8px 40px; cursor: pointer; user-select: all; -webkit-user-select: all; -moz-user-select: all;">
                    <span style="font-size: 12px; font-weight: 600; letter-spacing: 1.5px; color: #cfcfcf; text-transform: uppercase; user-select: all; -webkit-user-select: all;">
                        &#10697;&nbsp; Copy Code
                    </span>
                </td>
            </tr>
        </table>

        <p style="margin: 8px 0 0; font-size: 12px; color: #737373;">
            Tip: Tap or double-click the code above to select and copy it.
        </p>

        <p style="margin: 24px 0 0; font-size: 13px; color: #8a8a8a; line-height: 1.5;">
            This code is valid for <strong>10 minutes</strong>. If you did not request this code, you can safely disregard this email.
        </p>
    """

    html_content = _render_email_wrapper(
        header_title="EX SHARE",
        headline=headline,
        body_html=body_html
    )

    try:
        msg = EmailMultiAlternatives(subject, text_content, from_email, to)
        msg.attach_alternative(html_content, "text/html")
        msg.send()
    except Exception as e:
        logger.warning(f"Failed to deliver passwordless OTP email to {email}: {e}. OTP: {otp}")
        print(f"[AUTH EMAIL] Passwordless OTP for {email}: {otp}")
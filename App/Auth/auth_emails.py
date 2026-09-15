import requests
import random
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from celery import shared_task

# @shared_task
def send_registration_otp_email(identifier, otp):
    subject = "Your OTP Code"
    from_email = ""
    to = [identifier]

    text_content = f"Your OTP for registration is: {otp}"

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
            <div style="max-width: 600px; margin: auto; background: #ffffff; border-radius: 8px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                <h2 style="color: #007bff; text-align: center;">Registration OTP</h2>
                <p style="font-size: 16px; color: #333;">
                    Hello,<br><br>
                    Thank you for registering on <b</b> 🎉 <br>
                    Please use the OTP below to complete your registration:
                </p>
                <div style="text-align: center; margin: 20px 0;">
                    <span style="font-size: 26px; font-weight: bold; color: #007bff; padding: 12px 24px; border: 2px solid #007bff; display: inline-block; border-radius: 6px; border-style: dashed;">
                        {otp}
                    </span>
                </div>
                <p style="font-size: 14px; color: #555;">
                    This OTP is valid for <b>10 minutes</b>. Do not share it with anyone.
                </p>
                <p style="font-size: 12px; color: #aaa; text-align: center; margin-top: 30px;">
                    &copy; 2025
                </p>
            </div>
        </body>
    </html>
    """

    msg = EmailMultiAlternatives(subject, text_content, from_email, to)
    msg.attach_alternative(html_content, "text/html")
    msg.send()
    
def user_created_email(user, email):
    subject = "Welcome to - Account Created"
    from_email = ""
    to = [email]

    text_content = f"Hello {user.username},\n\nWelcome to! Your account has been successfully created."

    html_content = f""" 
    <html>
        <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
            <div style="max-width: 600px; margin: auto; background: #ffffff; border-radius: 8px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                <h2 style="color: #007bff; text-align: center;">Welcome to</h2>
                <p style="font-size: 16px; color: #333;">
                    Hello {user.username},<br><br>
                    Welcome to! Your account has been successfully created.
                </p>
                <p style="font-size: 12px; color: #aaa; text-align: center; margin-top: 30px;">
                    &copy; 2025
                </p>
            </div>
        </body>
    </html>
    """

    msg = EmailMultiAlternatives(subject, text_content, from_email, to)
    msg.attach_alternative(html_content, "text/html")
    msg.send()

def login_detected_email(user, email, ip_address, user_agent, login_time, notify_url_yes, notify_url_no):
    subject = "New Login Detected on Your Account"
    from_email = ""
    to = [email]

    text_content = f"Hello {user.username},\n\nA new login has been detected on your account. Please log in immediately."

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f6f9fc; line-height: 1.6;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f6f9fc; padding: 40px 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="max-width: 600px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);">
                    
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 40px 40px 30px; text-align: center;">
                            <div style="width: 64px; height: 64px; background-color: rgba(255, 255, 255, 0.2); border-radius: 50%; margin: 0 auto 20px; display: flex; align-items: center; justify-content: center;">
                                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z" fill="white"/>
                                </svg>
                            </div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 600; letter-spacing: -0.5px;">Security Alert</h1>
                            <p style="margin: 10px 0 0; color: rgba(255, 255, 255, 0.9); font-size: 16px;">New login detected on your account</p>
                        </td>
                    </tr>
                    
                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 24px; color: #1a1a1a; font-size: 16px;">
                                Hello <strong>{user.username}</strong>,
                            </p>
                            
                            <p style="margin: 0 0 32px; color: #4a5568; font-size: 15px;">
                                We detected a new sign-in to your account. If this was you, you can safely ignore this email. If you don't recognize this activity, please secure your account immediately.
                            </p>
                            
                            <!-- Login Details Card -->
                            <div style="background-color: #f8fafc; border-left: 4px solid #667eea; padding: 24px; border-radius: 8px; margin-bottom: 32px;">
                                <h3 style="margin: 0 0 16px; color: #2d3748; font-size: 16px; font-weight: 600;">Login Details</h3>
                                
                                <table width="100%" cellpadding="0" cellspacing="0" style="font-size: 14px;">
                                    <tr>
                                        <td style="padding: 8px 0; color: #718096; width: 120px; vertical-align: top;">
                                            <strong>Time:</strong>
                                        </td>
                                        <td style="padding: 8px 0; color: #2d3748;">
                                            {login_time}
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 8px 0; color: #718096; vertical-align: top;">
                                            <strong>Device:</strong>
                                        </td>
                                        <td style="padding: 8px 0; color: #2d3748;">
                                            {user_agent}
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 8px 0; color: #718096; vertical-align: top;">
                                            <strong>IP Address:</strong>
                                        </td>
                                        <td style="padding: 8px 0; color: #2d3748; font-family: 'Courier New', monospace;">
                                            {ip_address}
                                        </td>
                                    </tr>
                                </table>
                            </div>
                            
                            <!-- Question -->
                            <p style="margin: 0 0 20px; color: #2d3748; font-size: 16px; font-weight: 600; text-align: center;">
                                Was this you?
                            </p>
                            
                            <!-- Action Buttons -->
                            
                            
                            <!-- Security Notice -->
                            <div style="margin-top: 32px; padding: 20px; background-color: #fef3c7; border-radius: 8px; border: 1px solid #fbbf24;">
                                <p style="margin: 0; color: #92400e; font-size: 14px; line-height: 1.6;">
                                    <strong>Security Tip:</strong> If you didn't make this login, click "No, secure account" immediately to protect your information. We recommend changing your password and enabling two-factor authentication.
                                </p>
                            </div>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f8fafc; padding: 30px 40px; border-top: 1px solid #e2e8f0;">
                            <p style="margin: 0 0 8px; color: #718096; font-size: 13px; text-align: center;">
                                This is an automated security notification from.
                            </p>
                            <p style="margin: 0; color: #a0aec0; font-size: 12px; text-align: center;">
                                &copy; 2025. All rights reserved.
                            </p>
                        </td>
                    </tr>
                    
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
    """

    msg = EmailMultiAlternatives(subject, text_content, from_email, to)
    msg.attach_alternative(html_content, "text/html")
    msg.send()
    

def password_reset_success_email(user, email, new_password):
    subject = "Password Reset - "
    from_email = ""
    to = [email]

    text_content = f"Hello {user.username},\n\nYour password has been reset successfully."

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;")
            <div style="max-width: 600px; margin: auto; background: #ffffff; border-radius: 8px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);")
                <h2 style="color: #007bff; text-align: center;">Password Reset</h2>
                <p style="font-size: 16px; color: #333;")
                    Hello {user.username},<br><br>
                    Your password has been reset successfully.<br><br>
                    New password is {new_password}<br><br>
                    If you did not request this change, please contact our support team immediately.
                </p>
            </div>
        </body>
    </html>
    """

    msg = EmailMultiAlternatives(subject, text_content, from_email, to)
    msg.attach_alternative(html_content, "text/html")
    msg.send()


def forgot_password_otp_email(identifier, otp):
    subject = "Your OTP Code - "
    from_email = ""
    to = [identifier]

    text_content = f"Your OTP for password reset is: {otp}"

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
            <div style="max-width: 600px; margin: auto; background: #ffffff; border-radius: 8px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                <h2 style="color: #007bff; text-align: center;">Password Reset OTP</h2>
                <p style="font-size: 16px; color: #333;">
                    Hello,<br><br>
                    You requested a password reset on <b</b>. <br>
                    Please use the OTP below to complete your password reset:
                </p>
                <div style="text-align: center; margin: 20px 0;">
                    <span style="font-size: 26px; font-weight: bold; color: #007bff; padding: 12px 24px; border: 2px solid #007bff; display: inline-block; border-radius: 6px; border-style: dashed;">
                        {otp}
                    </span>
                </div>
                <p style="font-size: 14px; color: #555;">
                    This OTP is valid for <b>10 minutes</b>. Do not share it with anyone.
                </p>
                <p style="font-size: 12px; color: #aaa; text-align: center; margin-top: 30px;">
                    &copy; 2025
                </p>
            </div>
        </body>
    </html>
    """

    msg = EmailMultiAlternatives(subject, text_content, from_email, to)
    msg.attach_alternative(html_content, "text/html")
    msg.send()
    


def password_changed_email(user, email):
    subject = "Password Changed Successfully - "
    from_email = ""
    to = [email]

    text_content = f"Hello {user.username},\n\nYour password has been changed successfully."

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
            <div style="max-width: 600px; margin: auto; background: #ffffff; border-radius: 8px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                <h2 style="color: #007bff; text-align: center;">Password Changed</h2>
                <p style="font-size: 16px; color: #333;">
                    Hello {user.username},<br><br>
                    Your password has been changed successfully.<br><br>
                    If you did not make this change, please contact our support team immediately.
                </p>
            </div>
        </body>
    </html>
    """
    msg = EmailMultiAlternatives(subject, text_content, from_email, to)
    msg.attach_alternative(html_content, "text/html")
    msg.send()


def send_passwordless_otp_email(email, otp, is_existing_user=True):
    """
    Sends a 6-digit one-time password (OTP) for passwordless login or registration.
    """
    action_text = "sign in to your studio" if is_existing_user else "create your studio account"
    headline = "Your Studio Access Code" if is_existing_user else "Welcome to Atelier Studio"
    subject = f"{otp} is your verification code"

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '')
    to = [email]

    text_content = (
        f"Your verification code to {action_text} is: {otp}\n\n"
        f"This code will expire in 10 minutes. Do not share it with anyone."
    )

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0b0f19; color: #e2e8f0;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #0b0f19; padding: 40px 15px;">
            <tr>
                <td align="center">
                    <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 540px; background-color: #151c2e; border: 1px solid #1e293b; border-radius: 14px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
                        <!-- Header Banner -->
                        <tr>
                            <td style="background: linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #4338ca 100%); padding: 36px 30px; text-align: center;">
                                <div style="font-size: 11px; letter-spacing: 2.5px; text-transform: uppercase; color: #a5b4fc; font-weight: 700; margin-bottom: 8px;">
                                    LUMIÈRE STUDIO & ATELIER
                                </div>
                                <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 700; letter-spacing: -0.5px;">
                                    {headline}
                                </h1>
                            </td>
                        </tr>

                        <!-- Body Content -->
                        <tr>
                            <td style="padding: 36px 30px; text-align: center;">
                                <p style="margin: 0 0 20px; font-size: 15px; color: #cbd5e1; line-height: 1.6;">
                                    Use the secure one-time passcode below to <strong>{action_text}</strong>.
                                </p>

                                <!-- OTP Box -->
                                <div style="margin: 28px auto; display: inline-block; padding: 16px 36px; background-color: #0b0f19; border: 1.5px dashed #6366f1; border-radius: 10px;">
                                    <span style="font-family: 'Courier New', Courier, monospace; font-size: 34px; font-weight: 800; letter-spacing: 8px; color: #818cf8; display: block;">
                                        {otp}
                                    </span>
                                </div>

                                <p style="margin: 20px 0 0; font-size: 13px; color: #94a3b8; line-height: 1.5;">
                                    This code is valid for <strong>10 minutes</strong>. If you did not request this login code, you can safely disregard this email.
                                </p>
                            </td>
                        </tr>

                        <!-- Footer -->
                        <tr>
                            <td style="background-color: #0e1424; padding: 20px 30px; border-top: 1px solid #1e293b; text-align: center;">
                                <p style="margin: 0; font-size: 11px; color: #64748b;">
                                    &copy; 2026 Lumière Studio DAM Platform. All rights reserved.
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    try:
        msg = EmailMultiAlternatives(subject, text_content, from_email, to)
        msg.attach_alternative(html_content, "text/html")
        msg.send()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to deliver passwordless OTP email to {email}: {e}. OTP: {otp}")
        print(f"[AUTH EMAIL] Passwordless OTP for {email}: {otp}")
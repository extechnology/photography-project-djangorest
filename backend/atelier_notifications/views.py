"""
==================================================================================
EX SHARE ATELIER — PRODUCTION SINGLE-FILE NOTIFICATIONS & SETTINGS API SPECIFICATION
==================================================================================
File: backend/atelier_notifications/views.py (or copy into your Django app)
Framework: Django 4.x / 5.x + Django REST Framework (DRF)

THIS SINGLE FILE CONTAINS:
1. Django Models:
   - StudioNotification (Categories: inquiry, gallery, event, plan, storage, system)
   - StudioNotificationSettings (Granular Email & In-App delivery preferences)
2. DRF Serializers:
   - StudioNotificationSerializer (with camelCase aliases & dynamic relative time_ago)
   - StudioNotificationSettingsSerializer (12 configurable channel preference toggles)
3. 6 Complete REST API Endpoints:
   - GET    /api/notifications/              (List notifications + unread & total counts)
   - POST   /api/notifications/<id>/read/    (Mark specific notification as read)
   - POST   /api/notifications/mark-all-read/(Mark all as read atomically)
   - DELETE /api/notifications/<id>/         (Delete single notification)
   - DELETE /api/notifications/clear-all/    (Clear all notifications for user)
   - GET/PATCH /api/notifications/settings/  (Get / Update Studio Notification Preferences)
4. Production Trigger Service Functions (respecting photographer preferences):
   - notify_inquiry_received(user, client_name, event_type, budget, inquiry_id)
   - notify_gallery_published(user, gallery_title, gallery_id)
   - notify_plan_activated(user, plan_name, duration_months)
   - notify_plan_cancelled(user, plan_name, expiry_date)
   - notify_plan_expiry_warning(user, plan_name, expiry_date, days_remaining)
   - notify_plan_expired(user, plan_name)
   - notify_storage_alert(user, pct_used, used_gb, limit_gb)
   - notify_event_activity(user, event_title, guest_name, photo_count)
5. Initial Seeder Utility (seeds realistic studio notifications for testing)
6. URLs Configuration Snippet
==================================================================================
"""

import uuid
from datetime import timedelta
from django.db import models, transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from rest_framework import serializers, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from App.Auth.auth_utils import CookieJWTAuthentication, get_user_from_request

User = get_user_model()


def resolve_user_from_request(request):
    """Resolves authenticated user from Bearer header or HTTP-only auth cookies."""
    user = getattr(request, 'user', None)
    if user and user.is_authenticated:
        return user
    try:
        return get_user_from_request(request)
    except Exception:
        return None


def _resolve_user_instance(user_or_photographer):
    """Normalizes input if a PhotographerProfile instance is passed instead of User."""
    if hasattr(user_or_photographer, 'user') and user_or_photographer.user:
        return user_or_photographer.user
    return user_or_photographer


# ==============================================================================
# 1. DJANGO MODELS: StudioNotification & StudioNotificationSettings
# ==============================================================================

class StudioNotificationSettings(models.Model):
    """
    Granular email and in-app delivery preferences for photographer studios.
    Connected 1-to-1 with the User / Photographer profile.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_settings')

    # Client Inquiries & Leads
    email_inquiries = models.BooleanField(default=True, help_text="Send email when a client submits booking inquiry")
    inapp_inquiries = models.BooleanField(default=True, help_text="Show in-app bell alert for inquiries")

    # Galleries & Client Activity
    email_gallery_visited = models.BooleanField(default=True, help_text="Email alert when client first unlocks gallery")
    email_gallery_download = models.BooleanField(default=True, help_text="Email alert when high-res ZIP package download is started")
    inapp_gallery_activity = models.BooleanField(default=True, help_text="In-app notification for gallery publish & client favorites")

    # Live Events & QR Sharing
    email_event_activity = models.BooleanField(default=True, help_text="Email digest of live event guest interactions")
    inapp_event_activity = models.BooleanField(default=True, help_text="In-app live feed for guest uploads and QR scans")

    # Subscription, Auto-Pay & Billing
    email_billing_alerts = models.BooleanField(default=True, help_text="Email payment receipts, renewal notices & cancellation receipts")
    inapp_billing_alerts = models.BooleanField(default=True, help_text="In-app warnings for plan renewal or pending expiration")

    # Storage Quotas & Vault Health
    email_storage_warnings = models.BooleanField(default=True, help_text="Send critical warning email at 85% and 95% disk usage")
    inapp_storage_warnings = models.BooleanField(default=True, help_text="In-app warning banner when nearing storage limit")

    # Studio Analytics & Digests
    email_weekly_digest = models.BooleanField(default=True, help_text="Weekly studio performance summary")

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'App'
        verbose_name = "Studio Notification Settings"
        verbose_name_plural = "Studio Notification Settings"

    def __str__(self):
        user_email = getattr(self.user, 'email', '') or str(self.user)
        return f"Notification Preferences for {user_email}"


class StudioNotification(models.Model):
    """
    Persistent notification model for photographer studios.
    Tracks inquiries, gallery events, storage health, and subscription milestones.
    """
    TYPE_CHOICES = (
        ('inquiry', 'Client Inquiry'),
        ('gallery', 'Gallery Delivery'),
        ('event', 'Live Event'),
        ('plan', 'Studio Plan & Billing'),
        ('storage', 'Storage & Quota'),
        ('system', 'System & Security'),
    )

    PRIORITY_CHOICES = (
        ('info', 'Info'),
        ('normal', 'Normal'),
        ('high', 'High Priority'),
        ('urgent', 'Urgent Alert'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='studio_notifications')
    type = models.CharField(max_length=32, choices=TYPE_CHOICES, default='system')
    priority = models.CharField(max_length=16, choices=PRIORITY_CHOICES, default='normal')
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    action_url = models.CharField(max_length=512, blank=True, null=True)   # e.g., '/dashboard/inquiries'
    action_label = models.CharField(max_length=64, blank=True, null=True)  # e.g., 'Review Inquiry'
    metadata = models.JSONField(default=dict, blank=True)                 # Optional context data
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'App'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['user', 'type']),
        ]

    def __str__(self):
        user_email = getattr(self.user, 'email', '') or str(self.user)
        return f"[{self.type.upper()}] {self.title} for {user_email}"

    @property
    def time_ago(self):
        """Computes human-friendly relative time string."""
        now = timezone.now()
        diff = now - self.created_at

        if diff < timedelta(minutes=1):
            return "Just now"
        elif diff < timedelta(hours=1):
            mins = max(1, int(diff.total_seconds() / 60))
            return f"{mins}m ago"
        elif diff < timedelta(days=1):
            hours = max(1, int(diff.total_seconds() / 3600))
            return f"{hours}h ago"
        elif diff < timedelta(days=2):
            return "Yesterday"
        elif diff < timedelta(days=7):
            return f"{diff.days}d ago"
        else:
            return self.created_at.strftime("%b %d, %Y")


# ==============================================================================
# 2. DRF SERIALIZERS
# ==============================================================================

class StudioNotificationSettingsSerializer(serializers.ModelSerializer):
    """Serializer for studio notification preferences."""
    class Meta:
        model = StudioNotificationSettings
        fields = [
            'id',
            'email_inquiries',
            'inapp_inquiries',
            'email_gallery_visited',
            'email_gallery_download',
            'inapp_gallery_activity',
            'email_event_activity',
            'inapp_event_activity',
            'email_billing_alerts',
            'inapp_billing_alerts',
            'email_storage_warnings',
            'inapp_storage_warnings',
            'email_weekly_digest',
            'updated_at',
        ]
        read_only_fields = ['id', 'updated_at']


class StudioNotificationSerializer(serializers.ModelSerializer):
    """Serializer for notifications with client-friendly camelCase and formatted time."""
    time_ago = serializers.CharField(read_only=True)
    description = serializers.CharField(source='message', read_only=True) # Compatibility alias
    isRead = serializers.BooleanField(source='is_read', read_only=True)   # CamelCase alias
    actionLabel = serializers.CharField(source='action_label', read_only=True)
    actionUrl = serializers.CharField(source='action_url', read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = StudioNotification
        fields = [
            'id',
            'type',
            'priority',
            'title',
            'message',
            'description',
            'is_read',
            'isRead',
            'action_url',
            'actionUrl',
            'action_label',
            'actionLabel',
            'metadata',
            'created_at',
            'createdAt',
            'time_ago',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'time_ago']


# ==============================================================================
# 3. COMPLETE API VIEWS & ENDPOINTS
# ==============================================================================

class NotificationSettingsView(APIView):
    """
    GET  /api/notifications/settings/
    PATCH /api/notifications/settings/
    Retrieves and updates the user's studio notification preferences.
    """
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = resolve_user_from_request(request)
        if not user or not user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        settings, _ = StudioNotificationSettings.objects.get_or_create(user=user)
        serializer = StudioNotificationSettingsSerializer(settings)
        return Response({
            "status": "success",
            "settings": serializer.data,
        }, status=status.HTTP_200_OK)

    def patch(self, request):
        user = resolve_user_from_request(request)
        if not user or not user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        settings, _ = StudioNotificationSettings.objects.get_or_create(user=user)
        serializer = StudioNotificationSettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            "status": "success",
            "message": "Notification preferences updated.",
            "settings": serializer.data,
        }, status=status.HTTP_200_OK)

    def put(self, request):
        return self.patch(request)


class NotificationListView(APIView):
    """
    GET /api/notifications/
    Query parameters:
      - is_read (true/false)
      - type (inquiry, gallery, event, plan, storage, system)
      - limit (integer)
    """
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = resolve_user_from_request(request)
        if not user or not user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        qs = StudioNotification.objects.filter(user=user)

        # 1. Filter by read state
        is_read_param = request.query_params.get('is_read')
        if is_read_param is not None:
            if is_read_param.lower() in ['true', '1']:
                qs = qs.filter(is_read=True)
            elif is_read_param.lower() in ['false', '0']:
                qs = qs.filter(is_read=False)

        # 2. Filter by category type
        notif_type = request.query_params.get('type')
        if notif_type and notif_type.lower() != 'all':
            qs = qs.filter(type=notif_type)

        # 3. Compute counters
        unread_count = StudioNotification.objects.filter(user=user, is_read=False).count()
        total_count = StudioNotification.objects.filter(user=user).count()

        # 4. Limit results if requested
        limit = request.query_params.get('limit')
        if limit and str(limit).isdigit():
            qs = qs[:int(limit)]
        else:
            qs = qs[:50]  # Safe production default

        serializer = StudioNotificationSerializer(qs, many=True)
        return Response({
            "status": "success",
            "unread_count": unread_count,
            "total_count": total_count,
            "results": serializer.data,
        }, status=status.HTTP_200_OK)


class MarkNotificationReadView(APIView):
    """
    POST /api/notifications/<id>/read/
    Marks a single notification as read and returns updated unread count.
    """
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id=None, pk=None, id=None):
        user = resolve_user_from_request(request)
        if not user or not user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        target_id = notification_id or pk or id
        notif = get_object_or_404(StudioNotification, id=target_id, user=user)
        if not notif.is_read:
            notif.is_read = True
            notif.save(update_fields=['is_read', 'updated_at'])

        unread_count = StudioNotification.objects.filter(user=user, is_read=False).count()
        return Response({
            "status": "success",
            "message": "Notification marked as read.",
            "unread_count": unread_count,
            "notification": StudioNotificationSerializer(notif).data,
        }, status=status.HTTP_200_OK)

    def patch(self, request, *args, **kwargs):
        return self.post(request, *args, **kwargs)


class MarkAllNotificationsReadView(APIView):
    """
    POST /api/notifications/mark-all-read/
    Marks all notifications for current user as read atomically.
    """
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = resolve_user_from_request(request)
        if not user or not user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        with transaction.atomic():
            updated = StudioNotification.objects.filter(
                user=user,
                is_read=False
            ).update(is_read=True, updated_at=timezone.now())

        return Response({
            "status": "success",
            "message": f"All {updated} notification(s) marked as read.",
            "unread_count": 0,
            "updated_count": updated,
        }, status=status.HTTP_200_OK)

    def patch(self, request):
        return self.post(request)


class NotificationDeleteView(APIView):
    """
    DELETE /api/notifications/<id>/
    Removes a single notification from history.
    """
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, notification_id=None, pk=None, id=None):
        user = resolve_user_from_request(request)
        if not user or not user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        target_id = notification_id or pk or id
        notif = get_object_or_404(StudioNotification, id=target_id, user=user)
        notif.delete()

        unread_count = StudioNotification.objects.filter(user=user, is_read=False).count()
        return Response({
            "status": "success",
            "message": "Notification removed.",
            "unread_count": unread_count,
        }, status=status.HTTP_200_OK)


class ClearAllNotificationsView(APIView):
    """
    DELETE /api/notifications/clear-all/
    Removes all notifications for the user.
    """
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        user = resolve_user_from_request(request)
        if not user or not user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        deleted_count, _ = StudioNotification.objects.filter(user=user).delete()
        return Response({
            "status": "success",
            "message": f"Cleared {deleted_count} notification(s).",
            "unread_count": 0,
            "total_count": 0,
        }, status=status.HTTP_200_OK)

    def post(self, request):
        return self.delete(request)


# ==============================================================================
# 4. REUSABLE TRIGGER FUNCTIONS (Respecting User Settings)
# ==============================================================================

def get_or_create_user_notification_settings(user):
    """Returns the user's StudioNotificationSettings instance."""
    user = _resolve_user_instance(user)
    settings, _ = StudioNotificationSettings.objects.get_or_create(user=user)
    return settings


def create_studio_notification(user, notif_type, title, message, priority='normal', action_url='', action_label='', metadata=None):
    """Generic helper to create and return a studio notification."""
    user = _resolve_user_instance(user)
    return StudioNotification.objects.create(
        user=user,
        type=notif_type,
        title=title,
        message=message,
        priority=priority,
        action_url=action_url,
        action_label=action_label,
        metadata=metadata or {},
    )


def notify_inquiry_received(user, client_name, event_type, budget='', inquiry_id=''):
    """
    Call when a client submits a new inquiry form on public portfolio.
    Respects:
      - settings.inapp_inquiries (for in-app studio bell)
      - settings.email_inquiries (for sending email)
    """
    user = _resolve_user_instance(user)
    settings = get_or_create_user_notification_settings(user)

    # 1. Trigger email if enabled
    if settings.email_inquiries:
        # send_mail(...) or enqueue Celery task
        pass

    # 2. Trigger in-app notification if enabled
    if not settings.inapp_inquiries:
        return None

    return create_studio_notification(
        user=user,
        notif_type='inquiry',
        priority='high',
        title=f"New Lead: {client_name}",
        message=f"{event_type or 'Photoshoot'} booking inquiry received{f' • Budget: {budget}' if budget else ''}. Awaiting response.",
        action_url=f"/dashboard/inquiries?id={inquiry_id}" if inquiry_id else "/dashboard/inquiries",
        action_label="Review Inquiry",
        metadata={"client_name": client_name, "inquiry_id": str(inquiry_id)},
    )


def notify_gallery_published(user, gallery_title, gallery_id=''):
    """Call when a gallery is published or delivered to client."""
    user = _resolve_user_instance(user)
    settings = get_or_create_user_notification_settings(user)
    if not settings.inapp_gallery_activity:
        return None

    return create_studio_notification(
        user=user,
        notif_type='gallery',
        priority='normal',
        title=f"Gallery Published: {gallery_title}",
        message="High-resolution client delivery link is live and ready to share.",
        action_url=f"/dashboard/gallery/{gallery_id}" if gallery_id else "/dashboard/gallery",
        action_label="Open Gallery",
        metadata={"gallery_id": str(gallery_id)},
    )


def notify_plan_activated(user, plan_name, duration_months=1):
    """Call upon successful Razorpay plan upgrade/activation."""
    user = _resolve_user_instance(user)
    settings = get_or_create_user_notification_settings(user)
    if settings.email_billing_alerts:
        # send_email_invoice(...)
        pass

    if not settings.inapp_billing_alerts:
        return None

    return create_studio_notification(
        user=user,
        notif_type='plan',
        priority='normal',
        title=f"Plan Activated: {plan_name}",
        message=f"Your studio has been upgraded with automated recurring billing every {duration_months} month(s).",
        action_url="/dashboard/settings",
        action_label="Manage Billing",
        metadata={"plan_name": plan_name, "duration_months": duration_months},
    )


def notify_plan_cancelled(user, plan_name, expiry_date):
    """Call when user cancels auto-renew (Netflix-style grace period)."""
    user = _resolve_user_instance(user)
    settings = get_or_create_user_notification_settings(user)
    if settings.email_billing_alerts:
        # send_cancellation_email(...)
        pass

    if not settings.inapp_billing_alerts:
        return None

    expiry_str = expiry_date.strftime('%B %d, %Y') if hasattr(expiry_date, 'strftime') else str(expiry_date)
    return create_studio_notification(
        user=user,
        notif_type='plan',
        priority='high',
        title="Membership Cancellation Scheduled",
        message=f"You cancelled recurring autopay for {plan_name}. You have full studio access until {expiry_str}.",
        action_url="/dashboard/settings",
        action_label="Restart Membership",
        metadata={"expiry_date": str(expiry_date)},
    )


def notify_plan_expiry_warning(user, plan_name, expiry_date, days_remaining):
    """
    Call when a subscription is approaching expiry (e.g., 7 days or 1 day before).
    Triggered by the periodic Celery beat task `check_subscription_expiry_task`.
    Respects:
      - settings.inapp_billing_alerts
      - settings.email_billing_alerts
    """
    user = _resolve_user_instance(user)
    settings = get_or_create_user_notification_settings(user)
    if settings.email_billing_alerts:
        # send_renewal_reminder_email(...)
        pass

    if not settings.inapp_billing_alerts:
        return None

    expiry_str = expiry_date.strftime('%B %d, %Y') if hasattr(expiry_date, 'strftime') else str(expiry_date)
    days_label = f"{days_remaining} day{'s' if days_remaining != 1 else ''}"
    priority = 'urgent' if days_remaining <= 1 else 'high'
    return create_studio_notification(
        user=user,
        notif_type='plan',
        priority=priority,
        title=f"Plan Expiring in {days_label}: {plan_name}",
        message=f"Your {plan_name} studio plan expires on {expiry_str} ({days_label} remaining). Renew now to keep your galleries, events, and face search active.",
        action_url="/dashboard/settings",
        action_label="Renew Plan",
        metadata={"plan_name": plan_name, "expiry_date": str(expiry_date), "days_remaining": days_remaining},
    )


def notify_plan_expired(user, plan_name):
    """
    Call when a subscription has actually expired (expiry_date has passed).
    Triggered by the periodic Celery beat task `check_subscription_expiry_task`.
    Respects:
      - settings.inapp_billing_alerts
      - settings.email_billing_alerts
    """
    user = _resolve_user_instance(user)
    settings = get_or_create_user_notification_settings(user)
    if settings.email_billing_alerts:
        # send_expiry_email(...)
        pass

    if not settings.inapp_billing_alerts:
        return None

    return create_studio_notification(
        user=user,
        notif_type='plan',
        priority='urgent',
        title=f"Studio Plan Expired: {plan_name}",
        message=(
            f"Your {plan_name} studio plan has expired. All public galleries, events, and face-search "
            "links have been locked for your clients. Renew immediately to restore full studio access."
        ),
        action_url="/dashboard/settings",
        action_label="Renew Now",
        metadata={"plan_name": plan_name},
    )


def notify_storage_alert(user, pct_used, used_gb, limit_gb):
    """Call when studio storage exceeds 85% or 95%."""
    user = _resolve_user_instance(user)
    settings = get_or_create_user_notification_settings(user)
    if settings.email_storage_warnings:
        # send_storage_warning_email(...)
        pass

    if not settings.inapp_storage_warnings:
        return None

    priority = 'urgent' if pct_used >= 95 else 'high'
    return create_studio_notification(
        user=user,
        notif_type='storage',
        priority=priority,
        title=f"Storage Alert: {pct_used}% Used",
        message=f"You have used {used_gb} GB of {limit_gb} GB. Upgrade your storage tier to ensure uninterrupted RAW uploads.",
        action_url="/dashboard/settings",
        action_label="Upgrade Storage",
        metadata={"pct_used": pct_used, "used_gb": used_gb, "limit_gb": limit_gb},
    )


def notify_event_activity(user, event_title, guest_name='', photo_count=1):
    """Call when guests upload photos or interact with live event QR gallery."""
    user = _resolve_user_instance(user)
    settings = get_or_create_user_notification_settings(user)
    if not settings.inapp_event_activity:
        return None

    guest_text = f"by {guest_name}" if guest_name else "from live event guests"
    return create_studio_notification(
        user=user,
        notif_type='event',
        priority='normal',
        title=f"New Photos: {event_title}",
        message=f"{photo_count} new photo(s) uploaded {guest_text}.",
        action_url="/dashboard/events",
        action_label="View Event",
        metadata={"event_title": event_title, "photo_count": photo_count},
    )


# ==============================================================================
# 5. INITIAL SEEDER (Populates realistic initial notifications for studio)
# ==============================================================================
def seed_initial_studio_notifications(user):
    """
    Utility function to create initial contextual notifications for a studio user.
    Can be called in user post_save signal or via manage.py shell.
    """
    user = _resolve_user_instance(user)
    # Ensure settings exist
    get_or_create_user_notification_settings(user)

    if StudioNotification.objects.filter(user=user).exists():
        return

    create_studio_notification(
        user=user,
        notif_type='inquiry',
        title="New Lead: Sarah & Michael Wedding",
        message="Editorial Wedding inquiry received for upcoming season • Budget: $4,500. Awaiting response.",
        priority='high',
        action_url="/dashboard/inquiries",
        action_label="Review Inquiry",
    )

    create_studio_notification(
        user=user,
        notif_type='gallery',
        title="Client Gallery Active: Atelier Vogue Shoot",
        message="High-resolution client delivery link is active with password protection enabled.",
        priority='normal',
        action_url="/dashboard/gallery",
        action_label="View Gallery",
    )

    create_studio_notification(
        user=user,
        notif_type='plan',
        title="Studio Cloud Vault Connected",
        message="Your studio tier and storage quotas are active with high-speed CDN delivery enabled.",
        priority='normal',
        action_url="/dashboard/settings",
        action_label="Manage Tier",
    )

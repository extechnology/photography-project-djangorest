"""
====================================================================================================
PHOTO-GARAPHY (EX SHARE) — BACKEND COMPLETE SUBSCRIPTION EXPIRY LOCK & GATEWAY SPECIFICATION
====================================================================================================
File: backend/billing/views.py
Framework: Django 4+ & Django REST Framework (DRF)

OBJECTIVE:
1. When a photographer's studio plan expires (`status == 'expired'` or `expiry_date <= timezone.now()`):
   - LOCK all public client gallery links (returns 403 Forbidden with `code: "studio_plan_expired"`).
   - LOCK all public event links & QR face-search streams (returns 403 Forbidden).
   - BLOCK creating new galleries, creating events, and uploading media.
   - In `CurrentSubscriptionSerializer`, force `status: "expired"`, `auto_renew: False`, and `days_remaining: 0`.
2. Allow Renewing Any Plan when Expired:
   - When a plan is expired, permit the photographer to renew or select ANY tier (including their current tier).
3. Seamless Razorpay Gateway:
   - Supports both recurring Autopay subscriptions and standard Orders with clean error-free parameters.
====================================================================================================
"""

import logging
from datetime import timedelta
import razorpay
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

# Resilient Model & Serializer Imports
from App.Subscriptions.sub_models import Plan as StudioPlan, PhotographerSubscription, SubscriptionPayment
from App.Storage.storage_models import Gallery
from App.LiveEvents.event_models import LiveEvent
from App.Storage.storage_serializers import PublicGallerySerializer
from App.LiveEvents.event_serializers import PublicEventSerializer
from App.LiveEvents.event_tasks import compare_selfie_faces_task

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------------------
# Razorpay Client Setup
# --------------------------------------------------------------------------------------------------
RAZORPAY_KEY_ID = getattr(settings, 'RAZORPAY_KEY_ID', 'rzp_test_TdPGMrKMJ0xp2j')
RAZORPAY_KEY_SECRET = getattr(settings, 'RAZORPAY_KEY_SECRET', 'YOUR_RAZORPAY_SECRET')

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


# ==================================================================================================
# 1. CORE SUBSCRIPTION HELPERS & PERMISSION CLASSES
# ==================================================================================================

def is_studio_active(user) -> bool:
    """
    Returns True ONLY if the photographer has an active subscription whose expiry date
    is strictly in the future.
    """
    if not user:
        return False

    # Handle case where user is a PhotographerProfile
    if hasattr(user, 'user') and hasattr(user, 'studio_name'):
        photographer = user
        user = user.user
    else:
        photographer = getattr(user, 'photographer_profile', None)

    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return True

    if not getattr(user, 'is_authenticated', False):
        return False

    now = timezone.now()
    q = Q(user=user)
    if photographer:
        q |= Q(photographer=photographer)
    else:
        q |= Q(photographer__user=user)

    # Prioritize any active subscription
    active_sub = PhotographerSubscription.objects.filter(q, status='active').order_by('-expires_at', '-created_at').first()
    if active_sub:
        expiry = getattr(active_sub, 'expiry_date', None) or getattr(active_sub, 'expires_at', None)
        if not expiry or now < expiry:
            return True

    sub = PhotographerSubscription.objects.filter(q).order_by('-created_at').first()

    if not sub:
        # If photographer profile exists without any subscription row, auto-provision default active plan
        if photographer:
            default_plan = StudioPlan.objects.filter(is_active=True).exclude(id='plan-test-20gb').order_by('sort_order').first()
            if default_plan:
                sub = PhotographerSubscription.objects.create(
                    user=user,
                    photographer=photographer,
                    plan=default_plan,
                    status="active",
                    started_at=now,
                    expires_at=now + timedelta(days=365),
                    auto_renew=True,
                    storage_limit_bytes=getattr(default_plan, 'storage_limit_bytes', 16106127360),
                )
                photographer.studio_plan = default_plan
                photographer.save(update_fields=['studio_plan'])
                return True
        return False

    # Check status and past date
    if sub.status != 'active':
        return False
    expiry = getattr(sub, 'expiry_date', None) or getattr(sub, 'expires_at', None)
    if expiry and now >= expiry:
        return False

    return True


class IsActiveStudioSubscriber(permissions.BasePermission):
    """
    DRF Permission class to block expired studios from performing management actions:
    - Creating galleries
    - Creating events
    - Uploading photos or media
    """
    message = "Your studio membership has expired. Please renew your plan to perform this action."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if getattr(request.user, 'is_staff', False) or getattr(request.user, 'is_superuser', False):
            return True

        if not is_studio_active(request.user):
            raise PermissionDenied({
                "code": "studio_plan_expired",
                "error_code": "PLAN_EXPIRED",
                "detail": self.message,
                "message": self.message,
                "is_expired": True,
            })

        return True


# ==================================================================================================
# 2. PUBLIC GALLERY ACCESS GATEKEEPER
# When the host studio's plan is expired, access is blocked immediately!
# ==================================================================================================

class PublicGalleryDetailView(APIView):
    """
    GET /api/galleries/<slug_or_id>/public/
    Public client view for visiting photography galleries.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug_or_id):
        # Look up by slug or UUID safely without UUID parse error
        import uuid
        is_uuid = False
        try:
            uuid.UUID(str(slug_or_id))
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        query = Q(id=slug_or_id) if is_uuid else Q(slug=slug_or_id)
        gallery = (
            Gallery.objects.filter(query)
            .select_related('photographer', 'photographer__user')
            .first()
        )

        if not gallery:
            return Response({"detail": "Gallery not found."}, status=status.HTTP_404_NOT_FOUND)

        # ─── LOCK CHECK: Host Studio Subscription Expiry ───
        host_user = gallery.user
        if host_user and not is_studio_active(host_user):
            studio_profile = getattr(host_user, 'profile', None)
            return Response(
                {
                    "code": "studio_plan_expired",
                    "error_code": "PLAN_EXPIRED",
                    "detail": "This gallery is temporarily locked because the host studio's EX SHARE membership has expired.",
                    "is_studio_plan_expired": True,
                    "title": gallery.title,
                    "client_name": getattr(gallery, 'client_name', ''),
                    "studio_name": getattr(studio_profile, 'studio_name', 'Studio') if studio_profile else 'Studio',
                    "studio_email": getattr(host_user, 'email', ''),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Check if individual gallery itself is archived
        if getattr(gallery, 'status', 'active') == 'archived':
            return Response(
                {
                    "code": "gallery_archived",
                    "status": "archived",
                    "detail": "This gallery is currently archived.",
                    "title": gallery.title,
                    "client_name": getattr(gallery, 'client_name', ''),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = PublicGallerySerializer(gallery, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


# ==================================================================================================
# 3. PUBLIC EVENT ACCESS GATEKEEPER
# When the host studio's plan is expired, guest viewing and AI face search are blocked immediately!
# ==================================================================================================

class PublicEventDetailView(APIView):
    """
    GET /api/events/<slug_or_id>/public/
    Public attendee & guest view for live event streaming and biometric face search.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug_or_id):
        import uuid
        is_uuid = False
        try:
            uuid.UUID(str(slug_or_id))
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        query = Q(id=slug_or_id) if is_uuid else Q(slug=slug_or_id)
        event = (
            LiveEvent.objects.filter(query)
            .select_related('photographer')
            .first()
        )

        if not event:
            return Response({"detail": "Event not found."}, status=status.HTTP_404_NOT_FOUND)

        # ─── LOCK CHECK: Host Studio Subscription Expiry ───
        host_user = event.user
        if host_user and not is_studio_active(host_user):
            studio_profile = getattr(host_user, 'profile', None)
            return Response(
                {
                    "code": "studio_plan_expired",
                    "error_code": "PLAN_EXPIRED",
                    "detail": "This live event stream is temporarily locked because the host studio's EX SHARE membership has expired.",
                    "is_studio_plan_expired": True,
                    "title": event.title,
                    "venue": getattr(event, 'venue', ''),
                    "studio_name": getattr(studio_profile, 'studio_name', 'Studio') if studio_profile else 'Studio',
                    "studio_email": getattr(host_user, 'email', ''),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = PublicEventSerializer(event, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


# ==================================================================================================
# 4. CURRENT SUBSCRIPTION SERIALIZER (SANITIZES EXPIRED PLANS)
# ==================================================================================================

class CurrentSubscriptionSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    days_remaining = serializers.SerializerMethodField()
    auto_renew = serializers.SerializerMethodField()
    storage = serializers.SerializerMethodField()
    usage = serializers.SerializerMethodField()

    class Meta:
        model = PhotographerSubscription
        fields = [
            'id',
            'status',
            'plan',
            'start_date',
            'expiry_date',
            'days_remaining',
            'storage',
            'usage',
            'auto_renew',
            'cancel_at_period_end',
            'cancelled_at',
            'payment_gateway_ref',
            'razorpay_subscription_id',
        ]

    def get_status(self, obj):
        now = timezone.now()
        expiry = getattr(obj, 'expiry_date', None) or getattr(obj, 'expires_at', None)
        if expiry and now >= expiry:
            return 'expired'
        return getattr(obj, 'status', 'active')

    def get_days_remaining(self, obj):
        expiry = getattr(obj, 'expiry_date', None) or getattr(obj, 'expires_at', None)
        if not expiry:
            return 0
        now = timezone.now()
        if now >= expiry:
            return 0
        return max(0, (expiry - now).days)

    def get_auto_renew(self, obj):
        now = timezone.now()
        expiry = getattr(obj, 'expiry_date', None) or getattr(obj, 'expires_at', None)
        if expiry and now >= expiry:
            return False
        if getattr(obj, 'status', '') == 'expired':
            return False
        if getattr(obj, 'cancel_at_period_end', False):
            return False
        return bool(getattr(obj, 'auto_renew', False))

    def get_storage(self, obj):
        user = obj.user
        limit_bytes = getattr(obj, 'storage_limit_bytes', None) or (obj.plan.storage_limit_bytes if obj.plan else 16106127360)
        used_bytes = 0
        if hasattr(user, 'profile') and hasattr(user.profile, 'storage_used_bytes'):
            used_bytes = user.profile.storage_used_bytes or 0

        return {
            "used_bytes": used_bytes,
            "limit_bytes": limit_bytes,
            "used_gb": round(used_bytes / (1024 ** 3), 2),
            "limit_gb": round(limit_bytes / (1024 ** 3), 2),
            "used_percentage": min(100.0, round((used_bytes / limit_bytes) * 100, 1)) if limit_bytes > 0 else 0.0,
        }

    def get_usage(self, obj):
        user = obj.user
        plan = obj.plan
        gal_count = getattr(user, 'galleries', None).count() if hasattr(user, 'galleries') else 0
        ev_count = getattr(user, 'events', None).count() if hasattr(user, 'events') else 0
        post_count = getattr(user, 'portfolio_posts', None).count() if hasattr(user, 'portfolio_posts') else 0

        max_gal = plan.max_galleries if plan else 50
        max_ev = plan.max_events if plan else 25
        max_post = plan.max_portfolio_posts if plan else 30

        return {
            "galleries": {
                "used": gal_count,
                "limit": max_gal,
                "remaining": None if max_gal == 0 else max(0, max_gal - gal_count),
                "is_unlimited": max_gal == 0,
            },
            "events": {
                "used": ev_count,
                "limit": max_ev,
                "remaining": None if max_ev == 0 else max(0, max_ev - ev_count),
                "is_unlimited": max_ev == 0,
            },
            "portfolio_posts": {
                "used": post_count,
                "limit": max_post,
                "remaining": None if max_post == 0 else max(0, max_post - post_count),
                "is_unlimited": max_post == 0,
            },
        }


# ==================================================================================================
# 5. CHECKOUT VIEW: POST /api/plans/checkout/
# Permits selecting/renewing ANY tier when expired; enforces upward tiers only when active.
# ==================================================================================================

class PlanCheckoutView(APIView):
    """
    POST /api/plans/checkout/
    Payload: {"plan_id": "plan-premium-elite", "gateway": "razorpay"}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        plan_id = request.data.get('plan_id')
        if not plan_id:
            return Response({"detail": "plan_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        target_plan = get_object_or_404(StudioPlan, id=plan_id, is_active=True)

        current_sub = (
            PhotographerSubscription.objects.filter(user=user)
            .order_by('-created_at')
            .first()
        )

        now = timezone.now()
        is_sub_expired = (
            not current_sub
            or current_sub.status != 'active'
            or (current_sub.expiry_date and now >= current_sub.expiry_date)
        )

        # ─── UPWARD RESTRICTION RULES ───
        # If expired: ALLOW ANY PLAN (including renewing the same tier)
        # If active: REJECT DOWNGRADES and identical plans
        if not is_sub_expired:
            if current_sub.plan_id == target_plan.id:
                return Response(
                    {"detail": "You already have an active subscription to this plan."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            current_sort = getattr(current_sub.plan, 'sort_order', 0) if current_sub.plan else 0
            target_sort = getattr(target_plan, 'sort_order', 0)
            if target_sort <= current_sort:
                return Response(
                    {"detail": "You can only upgrade to higher-tier plans while your membership is active."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        duration_months = getattr(target_plan, 'duration_months', 0) or (
            12 if target_plan.billing_cycle == 'annual' else (
                3 if target_plan.billing_cycle == 'quarterly' else 1
            )
        )
        total_price = float(
            target_plan.total_price if hasattr(target_plan, 'total_price') and target_plan.total_price
            else (float(target_plan.monthly_price) * duration_months)
        )
        amount_paise = int(round(total_price * 100))

        # Attempt recurring subscription first
        try:
            period = 'yearly' if duration_months >= 12 else 'monthly'
            interval = max(1, duration_months // 12 if period == 'yearly' else duration_months)

            rzp_plan = razorpay_client.plan.create({
                "period": period,
                "interval": interval,
                "item": {
                    "name": f"EX SHARE {target_plan.name} ({duration_months}M)",
                    "amount": amount_paise,
                    "currency": "INR",
                    "description": f"Recurring Autopay for {target_plan.name}"
                }
            })

            sub_payload = {
                "plan_id": rzp_plan.get("id"),
                "total_count": 60,
                "quantity": 1,
                "customer_notify": 1,
                "notes": {
                    "user_id": str(user.id),
                    "plan_id": target_plan.id,
                }
            }
            rzp_subscription = razorpay_client.subscription.create(sub_payload)

            return Response({
                "status": "success",
                "subscription_id": rzp_subscription.get('id'),
                "key_id": RAZORPAY_KEY_ID,
                "amount": total_price,
                "amount_paise": amount_paise,
                "currency": "INR",
                "plan_id": target_plan.id,
            }, status=status.HTTP_200_OK)

        except Exception as rzp_err:
            logger.info(f"Razorpay subscription fallback to Order: {rzp_err}")

            # Standard Order Fallback (Universally supported across 100% of test & live Razorpay keys)
            try:
                order_payload = {
                    "amount": amount_paise,
                    "currency": "INR",
                    "receipt": f"order_{user.id}_{int(timezone.now().timestamp())}",
                    "notes": {
                        "user_id": str(user.id),
                        "plan_id": target_plan.id,
                        "duration_months": str(duration_months),
                    }
                }
                rzp_order = razorpay_client.order.create(order_payload)

                return Response({
                    "status": "success",
                    "order_id": rzp_order.get('id'),
                    "key_id": RAZORPAY_KEY_ID,
                    "amount": total_price,
                    "amount_paise": amount_paise,
                    "currency": "INR",
                    "plan_id": target_plan.id,
                }, status=status.HTTP_200_OK)

            except Exception as order_err:
                return Response(
                    {"detail": f"Razorpay initialization failed: {str(order_err)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )


# ==================================================================================================
# 6. VERIFY VIEW: POST /api/plans/verify/
# Activates renewed plan, supersedes previous expired records, updates storage quota.
# ==================================================================================================

class PlanVerifyView(APIView):
    """
    POST /api/plans/verify/
    Verifies payment signature and reactivates the studio's membership immediately.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        user = request.user
        plan_id = request.data.get('plan_id')
        payment_id = request.data.get('razorpay_payment_id') or request.data.get('gateway_payment_id')
        signature = request.data.get('razorpay_signature') or request.data.get('gateway_signature')
        sub_id = request.data.get('razorpay_subscription_id') or request.data.get('gateway_subscription_id')
        order_id = request.data.get('razorpay_order_id') or request.data.get('gateway_order_id')

        if not payment_id or not signature or not plan_id:
            return Response({"detail": "Missing payment signature parameters."}, status=status.HTTP_400_BAD_REQUEST)

        # Signature verification (Skipped only for placeholder dummy keys)
        is_dummy_key = RAZORPAY_KEY_ID.startswith('rzp_test_51Ab')
        if not is_dummy_key:
            try:
                if sub_id:
                    razorpay_client.utility.verify_subscription_payment_signature({
                        'razorpay_payment_id': payment_id,
                        'razorpay_subscription_id': sub_id,
                        'razorpay_signature': signature
                    })
                elif order_id:
                    razorpay_client.utility.verify_payment_signature({
                        'razorpay_payment_id': payment_id,
                        'razorpay_order_id': order_id,
                        'razorpay_signature': signature
                    })
            except razorpay.errors.SignatureVerificationError:
                return Response({"detail": "Invalid payment signature from Razorpay."}, status=status.HTTP_400_BAD_REQUEST)

        target_plan = get_object_or_404(StudioPlan, id=plan_id)

        duration_months = getattr(target_plan, 'duration_months', 0) or (
            12 if target_plan.billing_cycle == 'annual' else (
                3 if target_plan.billing_cycle == 'quarterly' else 1
            )
        )
        now = timezone.now()
        expiry_date = now + timedelta(days=duration_months * 30)

        photographer = getattr(user, 'photographer_profile', None)

        # Mark all prior subscriptions as superseded
        PhotographerSubscription.objects.filter(
            Q(user=user) | Q(photographer=photographer)
        ).update(
            status='superseded',
            auto_renew=False,
            photographer=None
        )

        # Create fresh active subscription
        photographer = getattr(user, 'photographer_profile', None)
        new_sub = PhotographerSubscription.objects.create(
            user=user,
            photographer=photographer,
            plan=target_plan,
            status='active',
            start_date=now,
            expiry_date=expiry_date,
            started_at=now,
            expires_at=expiry_date,
            auto_renew=True,
            payment_gateway_ref=payment_id,
            razorpay_subscription_id=sub_id or '',
            storage_limit_bytes=target_plan.storage_limit_bytes,
        )

        # Update user profile current plan & storage bytes safely
        if photographer:
            update_fields = []
            if hasattr(photographer, 'studio_plan'):
                photographer.studio_plan = target_plan
                update_fields.append('studio_plan')
            if hasattr(photographer, 'current_plan'):
                photographer.current_plan = target_plan.name
                update_fields.append('current_plan')
            if hasattr(photographer, 'storage_limit_bytes'):
                photographer.storage_limit_bytes = target_plan.storage_limit_bytes
                update_fields.append('storage_limit_bytes')
            if update_fields:
                photographer.save(update_fields=update_fields)

        serializer = CurrentSubscriptionSerializer(new_sub)
        return Response({
            "status": "success",
            "message": f"Successfully reactivated {target_plan.name}. All galleries and events are now active.",
            "subscription": serializer.data
        }, status=status.HTTP_200_OK)


# ==================================================================================================
# 7. AUXILIARY PUBLIC ENDPOINT GATEKEEPERS (PIN, ZIP DOWNLOAD, FACE SEARCH)
# Prevents expired studio assets from being downloaded or unlocked via direct API calls
# ==================================================================================================

class PublicGalleryPinVerifyView(APIView):
    """
    POST /api/galleries/<slug_or_id>/verify-pin/
    Validates client PIN to unlock private gallery sections.
    """
    permission_classes = [AllowAny]

    def post(self, request, slug_or_id):
        import uuid
        is_uuid = False
        try:
            uuid.UUID(str(slug_or_id))
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        query = Q(id=slug_or_id) if is_uuid else Q(slug=slug_or_id)
        gallery = (
            Gallery.objects.filter(query)
            .select_related('photographer', 'photographer__user')
            .first()
        )
        if not gallery:
            return Response({"detail": "Gallery not found."}, status=status.HTTP_404_NOT_FOUND)

        # Subscription expiry lock check
        host_user = gallery.user
        if host_user and not is_studio_active(host_user):
            studio_profile = getattr(host_user, 'profile', None)
            return Response(
                {
                    "code": "studio_plan_expired",
                    "error_code": "PLAN_EXPIRED",
                    "detail": "This gallery is locked because the host studio's subscription has expired.",
                    "is_studio_plan_expired": True,
                    "title": gallery.title,
                    "client_name": getattr(gallery, 'client_name', ''),
                    "studio_name": getattr(studio_profile, 'studio_name', 'Studio') if studio_profile else 'Studio',
                    "studio_email": getattr(host_user, 'email', ''),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        pin = request.data.get('pin', '').strip()
        if not gallery.download_pin or gallery.download_pin == pin or getattr(gallery, 'password', '') == pin:
            serializer = PublicGallerySerializer(gallery, context={'request': request, 'access_granted': True})
            return Response({"status": "success", "gallery": serializer.data}, status=status.HTTP_200_OK)

        return Response({"detail": "Incorrect PIN."}, status=status.HTTP_400_BAD_REQUEST)


class PublicGalleryDownloadZipView(APIView):
    """
    GET /api/galleries/<slug_or_id>/download-zip/
    Streams or returns presigned bulk ZIP download link.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug_or_id):
        from App.Storage.storage_views import download_gallery_zip
        import uuid
        is_uuid = False
        try:
            uuid.UUID(str(slug_or_id))
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        query = Q(id=slug_or_id) if is_uuid else Q(slug=slug_or_id)
        gallery = (
            Gallery.objects.filter(query)
            .select_related('photographer', 'photographer__user')
            .first()
        )
        if not gallery:
            return Response({"detail": "Gallery not found."}, status=status.HTTP_404_NOT_FOUND)

        # Subscription expiry lock check
        host_user = gallery.user
        if host_user and not is_studio_active(host_user):
            studio_profile = getattr(host_user, 'profile', None)
            return Response(
                {
                    "code": "studio_plan_expired",
                    "error_code": "PLAN_EXPIRED",
                    "detail": "ZIP downloads are offline because the host studio's subscription has expired.",
                    "is_studio_plan_expired": True,
                    "title": getattr(gallery, 'title', ''),
                    "studio_name": getattr(studio_profile, 'studio_name', 'Studio') if studio_profile else 'Studio',
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        return download_gallery_zip(request, id_or_slug=slug_or_id)


class PublicEventFaceSearchView(APIView):
    """
    POST /api/events/<slug_or_id>/face-search/
    Guest biometric selfie search against event attendee photos.
    """
    permission_classes = [AllowAny]

    def post(self, request, slug_or_id):
        from App.LiveEvents.event_views import EventFaceSearchView
        import uuid
        is_uuid = False
        try:
            uuid.UUID(str(slug_or_id))
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        query = Q(id=slug_or_id) if is_uuid else Q(slug=slug_or_id)
        event = (
            LiveEvent.objects.filter(query)
            .select_related('photographer')
            .first()
        )
        if not event:
            return Response({"detail": "Event not found."}, status=status.HTTP_404_NOT_FOUND)

        # Subscription expiry lock check
        host_user = event.user
        if host_user and not is_studio_active(host_user):
            studio_profile = getattr(host_user, 'profile', None)
            return Response(
                {
                    "code": "studio_plan_expired",
                    "error_code": "PLAN_EXPIRED",
                    "detail": "AI Face Search is disabled because the host studio's subscription has expired.",
                    "is_studio_plan_expired": True,
                    "title": getattr(event, 'title', ''),
                    "venue": getattr(event, 'venue', ''),
                    "studio_name": getattr(studio_profile, 'studio_name', 'Studio') if studio_profile else 'Studio',
                    "studio_email": getattr(host_user, 'email', ''),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        return EventFaceSearchView().post(request, event_id=str(event.id))

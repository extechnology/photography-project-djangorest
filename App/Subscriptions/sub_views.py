from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta

from App.Auth.auth_utils import get_user_from_request
from .sub_models import Plan, SubscriptionPlans, PhotographerSubscription, SubscriptionPayment
from .sub_serializers import (
    PlanSerializer,
    CurrentSubscriptionSerializer,
    CheckoutRequestSerializer,
    VerifyPaymentRequestSerializer,
    SubscriptionPlansSerializer,
    PhotographerSubscriptionSerializer,
    UpgradeSubscriptionSerializer,
)
from .sub_services import (
    activate_subscription,
    create_checkout_order,
    verify_payment_signature,
)


def get_photographer_from_request(request):
    user = request.user if hasattr(request, 'user') and request.user and request.user.is_authenticated else None
    if not user:
        try:
            user = get_user_from_request(request)
        except Exception:
            user = None
    if not user:
        return None, "Authentication required."
    
    try:
        photographer = getattr(user, 'photographer_profile', None)
    except Exception:
        photographer = None

    if not photographer:
        from App.Photographers.photo_models import PhotographerProfile
        display_name = getattr(user, 'fullname', '') or user.username or "Studio Owner"
        photographer, _ = PhotographerProfile.objects.get_or_create(
            user=user,
            defaults={
                "name": display_name,
                "email": user.email or "",
                "phone": getattr(user, 'phone', '') or "",
                "studio_name": getattr(user, 'studio_name', '') or f"{display_name}'s Studio",
                "occupation": "Photographer",
            }
        )
    return photographer, None



class PlanListView(APIView):
    """
    Public listing of active Studio Plans with features, pricing, and storage limits.
    GET /api/plans/  or  GET /api/subscriptions/plans/
    """
    permission_classes = [AllowAny]

    def get(self, request):
        plans = Plan.objects.filter(is_active=True).order_by('sort_order', 'total_price')
        # If no new Plan records exist yet, fall back to seeding or legacy plans
        if not plans.exists():
            legacy_plans = SubscriptionPlans.objects.all().order_by('price_monthly')
            if legacy_plans.exists():
                return Response(SubscriptionPlansSerializer(legacy_plans, many=True).data, status=status.HTTP_200_OK)

        serializer = PlanSerializer(plans, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CurrentSubscriptionView(APIView):
    """
    Retrieves the active studio subscription, days remaining, and real-time storage quota metrics.
    GET /api/plans/current/  or  GET /api/subscriptions/current/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        photographer, err = get_photographer_from_request(request)
        if err:
            status_code = status.HTTP_401_UNAUTHORIZED if err == "Authentication required." else status.HTTP_404_NOT_FOUND
            return Response({"detail": err}, status=status_code)

        default_plan = Plan.objects.filter(is_active=True).order_by('sort_order').first()

        subscription, created = PhotographerSubscription.objects.get_or_create(
            photographer=photographer,
            defaults={
                "plan": photographer.studio_plan or default_plan,
                "status": "active",
                "start_date": timezone.now(),
                "expiry_date": timezone.now() + timedelta(days=365),
                "auto_renew": True,
            }
        )

        # If subscription exists but plan is None (e.g. legacy subscription), link default plan
        if not subscription.plan and default_plan:
            subscription.plan = default_plan
            subscription.save(update_fields=['plan'])

        serializer = CurrentSubscriptionSerializer(subscription)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CheckoutView(APIView):
    """
    Initiates studio plan upgrade or renewal:
    - If gateway='direct': Instantly activates subscription and commits quota.
    - If gateway='razorpay': Returns order tokens for payment checkout.
    POST /api/plans/checkout/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        photographer, err = get_photographer_from_request(request)
        if err:
            status_code = status.HTTP_401_UNAUTHORIZED if err == "Authentication required." else status.HTTP_404_NOT_FOUND
            return Response({"detail": err}, status=status_code)

        serializer = CheckoutRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        plan_id = serializer.validated_data['plan_id']
        gateway = serializer.validated_data['gateway']

        try:
            plan = Plan.objects.get(id=plan_id, is_active=True)
        except Plan.DoesNotExist:
            return Response(
                {"detail": f"Studio plan '{plan_id}' does not exist or is inactive."},
                status=status.HTTP_404_NOT_FOUND
            )

        checkout_data = create_checkout_order(photographer, plan, gateway=gateway)

        if checkout_data.get('direct_activated'):
            sub_serializer = CurrentSubscriptionSerializer(checkout_data['subscription'])
            return Response({
                "status": "success",
                "message": f"Successfully activated {plan.name} directly.",
                "direct_activated": True,
                "subscription": sub_serializer.data,
            }, status=status.HTTP_200_OK)

        return Response(checkout_data, status=status.HTTP_200_OK)


class VerifyPaymentView(APIView):
    """
    Verifies payment gateway signature, activates the studio subscription,
    and recalculates storage quota.
    POST /api/plans/verify/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        photographer, err = get_photographer_from_request(request)
        if err:
            status_code = status.HTTP_401_UNAUTHORIZED if err == "Authentication required." else status.HTTP_404_NOT_FOUND
            return Response({"detail": err}, status=status_code)

        serializer = VerifyPaymentRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        plan_id = serializer.validated_data['plan_id']
        order_id = serializer.validated_data.get('gateway_order_id', '')
        payment_id = serializer.validated_data.get('gateway_payment_id', '')
        signature = serializer.validated_data.get('gateway_signature', '')

        try:
            plan = Plan.objects.get(id=plan_id, is_active=True)
        except Plan.DoesNotExist:
            return Response({"detail": f"Plan '{plan_id}' not found."}, status=status.HTTP_404_NOT_FOUND)

        # Signature verification
        is_valid_sig = verify_payment_signature(order_id, payment_id, signature)
        if not is_valid_sig:
            return Response(
                {"detail": "Payment verification failed: invalid signature."},
                status=status.HTTP_400_BAD_REQUEST
            )

        subscription, payment = activate_subscription(
            photographer=photographer,
            plan=plan,
            gateway='razorpay',
            gateway_payment_id=payment_id,
            order_id=order_id,
            signature=signature,
        )

        return Response({
            "status": "success",
            "message": f"Payment verified. {plan.name} subscription is now active.",
            "subscription": CurrentSubscriptionSerializer(subscription).data,
        }, status=status.HTTP_200_OK)


class CancelAutoRenewView(APIView):
    """
    Turns off auto-renewal for the photographer's current active studio subscription.
    POST /api/plans/cancel/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        photographer, err = get_photographer_from_request(request)
        if err:
            status_code = status.HTTP_401_UNAUTHORIZED if err == "Authentication required." else status.HTTP_404_NOT_FOUND
            return Response({"detail": err}, status=status_code)

        subscription = getattr(photographer, 'subscription', None)
        if not subscription:
            return Response({"detail": "No active subscription found to cancel."}, status=status.HTTP_404_NOT_FOUND)

        subscription.auto_renew = False
        subscription.save(update_fields=['auto_renew'])

        return Response({
            "status": "success",
            "message": "Auto-renewal has been turned off for your studio subscription.",
            "auto_renew": False,
        }, status=status.HTTP_200_OK)


# =============================================================================
# Legacy Upgrade View (Preserved for Backward Compatibility)
# =============================================================================

class UpgradeSubscriptionView(APIView):
    """
    Legacy upgrade endpoint for /api/subscriptions/upgrade/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        photographer, err = get_photographer_from_request(request)
        if err:
            status_code = status.HTTP_401_UNAUTHORIZED if err == "Authentication required." else status.HTTP_404_NOT_FOUND
            return Response({"detail": err}, status=status_code)

        plan_id = str(request.data.get('plan_id', ''))

        # Check new Plan model first
        target_plan = Plan.objects.filter(id=plan_id).first()
        if target_plan:
            subscription, _ = activate_subscription(photographer, target_plan, gateway='direct')
            return Response({
                "status": "success",
                "message": f"Successfully upgraded to {target_plan.name}.",
                "subscription": CurrentSubscriptionSerializer(subscription).data
            }, status=status.HTTP_200_OK)

        # Legacy fallback to SubscriptionPlans
        try:
            legacy_plan = SubscriptionPlans.objects.get(id=int(plan_id))
        except (SubscriptionPlans.DoesNotExist, ValueError):
            return Response({"detail": "Specified subscription plan does not exist."}, status=status.HTTP_404_NOT_FOUND)

        photographer.plan = legacy_plan
        photographer.storage_limit_bytes = legacy_plan.storage_limit_bytes
        photographer.save(update_fields=['plan', 'storage_limit_bytes'])

        subscription, _ = PhotographerSubscription.objects.update_or_create(
            photographer=photographer,
            defaults={
                "legacy_plan": legacy_plan,
                "status": "active",
                "expiry_date": timezone.now() + timedelta(days=365),
                "auto_renew": True
            }
        )

        return Response({
            "status": "success",
            "message": f"Successfully upgraded to {legacy_plan.name}.",
            "subscription": PhotographerSubscriptionSerializer(subscription).data
        }, status=status.HTTP_200_OK)

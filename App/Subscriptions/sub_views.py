from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.utils import timezone
from datetime import timedelta

from .sub_models import SubscriptionPlans, PhotographerSubscription
from .sub_serializers import (
    SubscriptionPlansSerializer,
    PhotographerSubscriptionSerializer,
    UpgradeSubscriptionSerializer,
)


class SubscriptionPlansListView(APIView):
    """
    Public listing of subscription plans and tiers.
    GET /api/subscriptions/plans/
    """
    permission_classes = [AllowAny]

    def get(self, request):
        plans = SubscriptionPlans.objects.all().order_by('price_monthly')
        serializer = SubscriptionPlansSerializer(plans, many=True)
        return Response({
            "status": "success",
            "count": plans.count(),
            "results": serializer.data
        })


class CurrentSubscriptionView(APIView):
    """
    Retrieves the active subscription, billing status, and live quota metrics for the authenticated photographer.
    GET /api/subscriptions/current/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        photographer = getattr(user, 'photographer_profile', None)
        if not photographer:
            return Response(
                {"detail": "Photographer profile not found for this account."},
                status=status.HTTP_404_NOT_FOUND
            )

        subscription, _ = PhotographerSubscription.objects.get_or_create(
            photographer=photographer,
            defaults={
                "plan": photographer.plan or SubscriptionPlans.objects.filter(tier='pro').first() or SubscriptionPlans.objects.first(),
                "status": "active",
                "expires_at": timezone.now() + timedelta(days=365)
            }
        )

        serializer = PhotographerSubscriptionSerializer(subscription)
        return Response({
            "status": "success",
            "subscription": serializer.data
        })


class UpgradeSubscriptionView(APIView):
    """
    Upgrades or modifies the photographer's subscription plan.
    POST /api/subscriptions/upgrade/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        photographer = getattr(user, 'photographer_profile', None)
        if not photographer:
            return Response(
                {"detail": "Photographer profile not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = UpgradeSubscriptionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        plan_id = serializer.validated_data['plan_id']
        billing_cycle = serializer.validated_data['billing_cycle']

        try:
            target_plan = SubscriptionPlans.objects.get(id=plan_id)
        except SubscriptionPlans.DoesNotExist:
            return Response(
                {"detail": "Specified subscription plan does not exist."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Update photographer profile linkage
        photographer.plan = target_plan
        photographer.save(update_fields=['plan'])

        # Update or create active subscription record
        duration_days = 365 if billing_cycle == 'annual' else 30
        subscription, _ = PhotographerSubscription.objects.update_or_create(
            photographer=photographer,
            defaults={
                "plan": target_plan,
                "status": "active",
                "expires_at": timezone.now() + timedelta(days=duration_days),
                "auto_renew": True
            }
        )

        return Response({
            "status": "success",
            "message": f"Successfully upgraded to {target_plan.name} ({billing_cycle}).",
            "subscription": PhotographerSubscriptionSerializer(subscription).data
        }, status=status.HTTP_200_OK)

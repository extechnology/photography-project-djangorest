from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model

from App.Subscriptions.sub_models import SubscriptionPayment, PhotographerSubscription, Plan
from App.Photographers.photo_models import PhotographerProfile

User = get_user_model()


class AdminTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom JWT Token Serializer that supports authentication with username, email, or phone,
    and returns token pair with embedded user profile metadata.
    """
    def validate(self, attrs):
        # Support email or phone passed as username
        ident = attrs.get('username') or attrs.get('email') or attrs.get('phone')
        if ident:
            attrs['username'] = ident

        data = super().validate(attrs)

        user = self.user
        fullname = (
            getattr(user, 'fullname', '')
            or f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
            or user.username
            or user.email
            or 'Administrator'
        )

        data['token'] = data['access']
        data['user'] = {
            'id': user.id,
            'unique_id': str(getattr(user, 'unique_id', user.id)),
            'username': user.username or '',
            'email': user.email or '',
            'fullname': fullname,
            'role': getattr(user, 'role', 'admin'),
            'is_staff': getattr(user, 'is_staff', False),
            'is_superuser': getattr(user, 'is_superuser', False),
        }
        return data


class AdminUserItemSerializer(serializers.ModelSerializer):
    """
    Comprehensive serializer for the Admin Users & Studios Directory.
    """
    unique_id = serializers.SerializerMethodField()
    fullname = serializers.SerializerMethodField()
    studio_name = serializers.SerializerMethodField()
    plan_name = serializers.SerializerMethodField()
    subscription_status = serializers.SerializerMethodField()
    storage_used_bytes = serializers.SerializerMethodField()
    storage_used_gb = serializers.SerializerMethodField()
    galleries_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'unique_id',
            'username',
            'email',
            'phone',
            'fullname',
            'role',
            'studio_name',
            'plan_name',
            'subscription_status',
            'storage_used_bytes',
            'storage_used_gb',
            'galleries_count',
            'is_active',
            'is_staff',
            'is_superuser',
            'is_email_verified',
            'is_phone_verified',
            'date_joined',
            'last_login',
        ]

    def get_unique_id(self, obj):
        return str(getattr(obj, 'unique_id', obj.id))

    def get_fullname(self, obj):
        name = getattr(obj, 'fullname', '') or f"{getattr(obj, 'first_name', '')} {getattr(obj, 'last_name', '')}".strip()
        return name or obj.username or obj.email or ''

    def get_studio_name(self, obj):
        profile = getattr(obj, 'photographer_profile', None)
        if profile and getattr(profile, 'studio_name', None):
            return profile.studio_name
        studio = getattr(obj, 'studio', None)
        if studio:
            return getattr(studio, 'name', '') or getattr(studio, 'studio_name', '')
        return getattr(obj, 'studio_name', '') or 'Individual Creator'

    def get_plan_name(self, obj):
        sub = getattr(obj, 'subscriptions', None)
        if sub:
            active_sub = sub.order_by('-created_at').first()
            if active_sub and active_sub.plan:
                return active_sub.plan.name
        profile = getattr(obj, 'photographer_profile', None)
        if profile and getattr(profile, 'studio_plan', None):
            return profile.studio_plan.name
        elif profile and getattr(profile, 'plan', None):
            return profile.plan.name
        return 'Standard Tier'

    def get_subscription_status(self, obj):
        sub = getattr(obj, 'subscriptions', None)
        if sub:
            active_sub = sub.order_by('-created_at').first()
            if active_sub:
                return active_sub.status
        return 'active' if getattr(obj, 'is_active', True) else 'expired'

    def get_storage_used_bytes(self, obj):
        profile = getattr(obj, 'photographer_profile', None)
        return getattr(profile, 'storage_used_bytes', 0) if profile else getattr(obj, 'total_storage_bytes', 0) or 0

    def get_storage_used_gb(self, obj):
        used = self.get_storage_used_bytes(obj)
        return round(used / (1024 ** 3), 2) if used else 0.0

    def get_galleries_count(self, obj):
        profile = getattr(obj, 'photographer_profile', None)
        if profile and hasattr(profile, 'galleries'):
            return profile.galleries.count()
        return getattr(obj, 'galleries_count', 0) or (obj.galleries.count() if hasattr(obj, 'galleries') else 0)


class AdminPaymentItemSerializer(serializers.ModelSerializer):
    """
    Serializer for billing transactions and payments log.
    """
    user_email = serializers.SerializerMethodField()
    user_id = serializers.SerializerMethodField()
    studio_name = serializers.SerializerMethodField()
    plan_name = serializers.SerializerMethodField()
    plan_tier = serializers.SerializerMethodField()
    plan_cycle = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPayment
        fields = [
            'id',
            'gateway_order_id',
            'gateway_payment_id',
            'amount',
            'currency',
            'gateway',
            'status',
            'invoice_url',
            'paid_at',
            'created_at',
            'user_id',
            'user_email',
            'studio_name',
            'plan_name',
            'plan_tier',
            'plan_cycle',
        ]

    def get_user_email(self, obj):
        if obj.subscription and obj.subscription.user:
            return obj.subscription.user.email or ''
        return ''

    def get_user_id(self, obj):
        if obj.subscription and obj.subscription.user_id:
            return obj.subscription.user_id
        return None

    def get_studio_name(self, obj):
        if obj.subscription and obj.subscription.photographer:
            return obj.subscription.photographer.studio_name or obj.subscription.photographer.name or ''
        return ''

    def get_plan_name(self, obj):
        if obj.plan:
            return obj.plan.name
        if obj.subscription and obj.subscription.plan:
            return obj.subscription.plan.name
        return 'Standard Plan'

    def get_plan_tier(self, obj):
        if obj.plan:
            return obj.plan.tier
        if obj.subscription and obj.subscription.plan:
            return obj.subscription.plan.tier
        return 'standard'

    def get_plan_cycle(self, obj):
        if obj.plan:
            return obj.plan.billing_cycle
        if obj.subscription and obj.subscription.plan:
            return obj.subscription.plan.billing_cycle
        return 'quarterly'


# Backward-compatible aliases
AdminUserListSerializer = AdminUserItemSerializer
AdminPaymentListSerializer = AdminPaymentItemSerializer

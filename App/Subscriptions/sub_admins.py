from django.contrib import admin
from .sub_models import SubscriptionPlans, PhotographerSubscription


@admin.register(SubscriptionPlans)
class SubscriptionPlansAdmin(admin.ModelAdmin):
    list_display = ('name', 'tier', 'billing_cycle', 'price_monthly', 'storage_limit_bytes', 'video_delivery_enabled', 'face_search_enabled')
    list_filter = ('tier', 'billing_cycle', 'video_delivery_enabled', 'face_search_enabled')
    search_fields = ('name', 'tier')


@admin.register(PhotographerSubscription)
class PhotographerSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'photographer', 'plan', 'status', 'started_at', 'expires_at', 'auto_renew')
    list_filter = ('status', 'auto_renew', 'plan')
    search_fields = ('photographer__name', 'photographer__studio_name', 'payment_gateway_ref')

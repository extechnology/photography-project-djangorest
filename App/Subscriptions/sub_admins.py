from django.contrib import admin
from .sub_models import Plan, SubscriptionPlans, PhotographerSubscription, SubscriptionPayment


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'tier', 'billing_cycle', 'monthly_price', 'total_price', 'storage_limit_bytes', 'tag', 'is_active', 'sort_order')
    list_filter = ('tier', 'billing_cycle', 'is_active', 'tag_type')
    search_fields = ('id', 'name', 'subtitle')
    ordering = ('sort_order', 'total_price')


@admin.register(SubscriptionPlans)
class SubscriptionPlansAdmin(admin.ModelAdmin):
    list_display = ('name', 'tier', 'billing_cycle', 'price_monthly', 'storage_limit_bytes', 'video_delivery_enabled', 'face_search_enabled')
    list_filter = ('tier', 'billing_cycle', 'video_delivery_enabled', 'face_search_enabled')
    search_fields = ('name', 'tier')


@admin.register(PhotographerSubscription)
class PhotographerSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'photographer', 'plan', 'status', 'start_date', 'expiry_date', 'auto_renew')
    list_filter = ('status', 'auto_renew', 'plan')
    search_fields = ('photographer__name', 'photographer__studio_name', 'payment_gateway_ref')


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'subscription', 'plan', 'amount', 'currency', 'gateway', 'gateway_order_id', 'status', 'paid_at', 'created_at')
    list_filter = ('status', 'gateway', 'currency')
    search_fields = ('gateway_order_id', 'gateway_payment_id', 'subscription__photographer__name')

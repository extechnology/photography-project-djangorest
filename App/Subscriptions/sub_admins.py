from django.contrib import admin
from .sub_models import Plan, SubscriptionPlans, PhotographerSubscription, SubscriptionPayment


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name',
        'tier',
        'billing_cycle',
        'monthly_price',
        'total_price',
        'ai_culling_enabled',
        'storage_limit_bytes',
        'is_active',
        'sort_order'
    )
    list_filter = ('ai_culling_enabled', 'tier', 'billing_cycle', 'is_active', 'tag_type')
    search_fields = ('id', 'name', 'subtitle')
    list_editable = ('ai_culling_enabled', 'is_active')
    ordering = ('sort_order', 'total_price')
    fieldsets = (
        ('Plan Details', {
            'fields': ('id', 'name', 'subtitle', 'tier', 'billing_cycle', 'duration_months', 'monthly_price', 'original_monthly_price', 'total_price', 'currency', 'tag', 'tag_type', 'cta_text', 'is_active', 'is_popular', 'sort_order')
        }),
        ('Storage Quota', {
            'fields': ('image_storage_gb', 'video_storage_gb', 'storage_limit_bytes', 'can_upgrade_storage', 'max_upgrade_image_gb')
        }),
        ('Feature Capabilities', {
            'fields': ('ai_culling_enabled', 'face_search_enabled', 'watermark_enabled', 'max_galleries', 'gallery_expiry_days', 'allowed_templates', 'allowed_portfolio_templates', 'max_events', 'max_portfolio_posts', 'has_full_inquiry_access', 'max_inquiries', 'features')
        }),
    )


@admin.register(SubscriptionPlans)
class SubscriptionPlansAdmin(admin.ModelAdmin):
    list_display = ('name', 'tier', 'billing_cycle', 'price_monthly', 'ai_culling_enabled', 'storage_limit_bytes', 'video_delivery_enabled', 'face_search_enabled')
    list_filter = ('ai_culling_enabled', 'tier', 'billing_cycle', 'video_delivery_enabled', 'face_search_enabled')
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

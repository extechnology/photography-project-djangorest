from django.contrib import admin
from .models import PortfolioConfig, PortfolioWork, PortfolioWorkPhoto, PortfolioInquiry, PortfolioView


class PortfolioWorkPhotoInline(admin.TabularInline):
    model = PortfolioWorkPhoto
    extra = 1
    fields = ('order', 'photo_url', 'caption')


@admin.register(PortfolioWork)
class PortfolioWorkAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'portfolio', 'year', 'location', 'order', 'created_at')
    list_filter = ('category', 'year', 'portfolio')
    search_fields = ('title', 'location', 'description', 'portfolio__studio_name')
    inlines = [PortfolioWorkPhotoInline]


class PortfolioWorkInline(admin.TabularInline):
    model = PortfolioWork
    extra = 0
    fields = ('title', 'category', 'year', 'order')
    show_change_link = True


@admin.register(PortfolioConfig)
class PortfolioConfigAdmin(admin.ModelAdmin):
    list_display = ('studio_name', 'artist_name', 'template_id', 'user', 'location', 'is_booking_open', 'updated_at')
    list_filter = ('template_id', 'is_booking_open')
    search_fields = ('studio_name', 'artist_name', 'user__username', 'user__email', 'location')
    inlines = [PortfolioWorkInline]


@admin.register(PortfolioInquiry)
class PortfolioInquiryAdmin(admin.ModelAdmin):
    list_display = ('client_name', 'event_type', 'photographer', 'status', 'budget', 'event_date', 'created_at')
    list_filter = ('status', 'event_type', 'created_at')
    search_fields = ('client_name', 'client_email', 'client_phone', 'message', 'photographer__username')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PortfolioView)
class PortfolioViewAdmin(admin.ModelAdmin):
    list_display = ('session_id', 'photographer', 'device', 'city', 'country', 'page_section', 'project_id', 'created_at')
    list_filter = ('device', 'country', 'page_section', 'created_at')
    search_fields = ('session_id', 'photographer__username', 'city', 'country', 'referrer', 'project_id')
    readonly_fields = ('id', 'created_at')


from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .auth_models import User, PasswordlessLoginOTP


class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "phone")


class CustomUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = ("username", "email", "phone", "is_active", "is_staff", "is_superuser")


class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = CustomUserChangeForm
    add_form = CustomUserCreationForm
    change_password_form = AdminPasswordChangeForm
    model = User

    list_display = ("unique_id", "username", "email", "phone", "role", "is_active", "is_email_verified", "is_phone_verified")
    list_display_links = ("username",)
    list_filter = ("role", "is_staff", "is_active", "is_superuser", "is_email_verified", "is_phone_verified")
    search_fields = ("username", "email", "phone", "fullname")
    ordering = ("-date_joined",)
    show_full_result_count = True
    list_filter_submit = True
    compressed_fields = True
    warn_unsaved_form = True

    fieldsets = (
        (None, {"fields": ("username", "email", "phone", "password")}),
        (_("Profile & Clearance"), {"fields": ("fullname", "role", "is_active", "is_staff", "is_superuser", "is_email_verified", "is_phone_verified")}),
        (_("Permissions & Groups"), {"fields": ("groups", "user_permissions"), "classes": ("collapse",)}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "email", "phone", "role", "password1", "password2", "is_staff", "is_active", "is_email_verified", "is_phone_verified"),
        }),
    )


admin.site.register(User, UserAdmin)


@admin.register(PasswordlessLoginOTP)
class PasswordlessLoginOTPAdmin(ModelAdmin):
    list_display = ("email", "otp", "is_verified", "created_at")
    list_filter = ("is_verified", "created_at")
    search_fields = ("email", "otp")
    readonly_fields = ("created_at",)
    list_filter_submit = True
    compressed_fields = True
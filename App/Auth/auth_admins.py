from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField, AdminPasswordChangeForm
from django import forms
from django.urls import path
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from .auth_models import *


class UserCreationForm(forms.ModelForm):
    """Form for creating new users in the admin."""
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm Password", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("username", "email", "phone")

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords don't match")
        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserChangeForm(forms.ModelForm):
    """Form for updating users in the admin."""
    password = ReadOnlyPasswordHashField(
        label="Password",
        help_text=_("Passwords are not stored in plain text. "
                    "You can change the password using <a href='../password/'>this form</a>.")
    )

    class Meta:
        model = User
        fields = ("username", "email", "phone", "password", "is_active", "is_staff", "is_superuser")

    def clean_password(self):
        return self.initial["password"]


# --- Admin ---

class UserAdmin(BaseUserAdmin):
    add_form = UserCreationForm
    form = UserChangeForm
    model = User

    list_display        = ("unique_id", "username", "email", "phone", "is_active", 'is_email_verified', 'is_phone_verified')
    list_display_links  = ("username",)
    list_filter         = ("is_staff", "is_active", "is_superuser", "is_email_verified", "is_phone_verified")
    search_fields       = ("username", "email", "phone")
    ordering            = ("id",)
    show_full_result_count = True
    list_filter_submit  = True
    compressed_fields   = True

    fieldsets = (
        (None, {"fields": ("username", "email", "phone", "password")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions", 'is_email_verified', 'is_phone_verified')}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "email", "phone", "password1", "password2", "is_staff", "is_active", 'is_email_verified', 'is_phone_verified'),
        }),
    )

    # ✅ Reset password view
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<id>/password/",
                self.admin_site.admin_view(self.user_change_password),
                name="user_change_password",
            ),
        ]
        return custom_urls + urls

    def user_change_password(self, request, id, form_url=""):
        user = self.get_object(request, id)
        if not user:
            return redirect("..")

        if request.method == "POST":
            form = AdminPasswordChangeForm(user, request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, _("Password changed successfully."))
                return redirect("..")
        else:
            form = AdminPasswordChangeForm(user)

        context = {
            "title": _("Change password"),
            "form": form,
            "is_popup": False,
            "add": False,
            "change": True,
            "has_view_permission": True,
            "opts": self.model._meta,
            "original": user,
        }
        return render(request, "admin/auth/user/change_password.html", context)


admin.site.register(User, UserAdmin)
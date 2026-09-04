from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db.models import Q
import uuid
from django.utils import timezone
from datetime import timedelta

class CustomUserManager(BaseUserManager):

    def _normalize_fields(self, username, email, phone):
        """Coerce blank strings to None so unique=True + null=True doesn't
        collide on empty-string duplicates."""
        username = username or None
        email = self.normalize_email(email) if email else None
        phone = phone or None
        return username, email, phone

    def create_user(self, username=None, email=None, phone=None, password=None, **extra_fields):
        username, email, phone = self._normalize_fields(username, email, phone)

        if not (username or email or phone):
            raise ValueError("User must have either a username, email, or phone")

        user = self.model(
            username=username,
            email=email,
            phone=phone,
            **extra_fields
        )
        user.set_password(password)  # handles password=None -> set_unusable_password
        user.full_clean(exclude=["password"])  # runs the CheckConstraint-backed validation too
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email=None, phone=None, password=None, **extra_fields):
        if not password:
            raise ValueError("Superuser must have a password")
        if not email:
            raise ValueError("Superuser must have an email")

        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", User.Role.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")

        return self.create_user(username=username, email=email, phone=phone, password=password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        STAFF = "staff", "Staff"
        USER = "user", "User"

    unique_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    id = models.AutoField(primary_key=True)

    username = models.CharField(max_length=150, unique=True, null=True, blank=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    phone = models.CharField(max_length=20, unique=True, null=True, blank=True)

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.USER,
        db_index=True,
    )

    fullname = models.CharField(max_length=255, null=True, blank=True)

    is_email_verified = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)

    date_joined = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_admin = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = CustomUserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email", "phone"]

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(username__isnull=False)
                    | Q(email__isnull=False)
                    | Q(phone__isnull=False)
                ),
                name="user_must_have_identifier",
            )
        ]

    def __str__(self):
        return self.username or self.email or self.phone or "User"

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN

    @property
    def is_staff_role(self):
        return self.role == self.Role.STAFF

class RegistrationOTP(models.Model):
    identifier = models.CharField(max_length=255)  
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.identifier} - {self.otp}"
    
    def save(self, *args, **kwargs):
        from django.utils import timezone
        from datetime import timedelta

        # Delete old OTPs for the same identifier
        RegistrationOTP.objects.filter(identifier=self.identifier).delete()
        super().save(*args, **kwargs)

    def is_valid(self, input_otp):
        # OTP is valid for 10 minutes

        if self.otp != input_otp:
            return False
        if timezone.now() > self.created_at + timedelta(minutes=10):
            return False
        return True


    
class ResetPasswordOTP(models.Model):
    identifier = models.CharField(max_length=255)  # can be email or phone
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.identifier} - {self.otp}"
    
    def save(self, *args, **kwargs):
        from django.utils import timezone
        from datetime import timedelta

        ResetPasswordOTP.objects.filter(identifier=self.identifier).delete()
        super().save(*args, **kwargs)
        
    def is_valid(self, input_otp):

        if self.otp != input_otp:
            return False
        if timezone.now() > self.created_at + timedelta(minutes=10):
            return False
        return True

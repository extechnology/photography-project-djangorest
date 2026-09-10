from django.db import models
from App.Auth.auth_models import User
from App.Subscriptions.sub_models import SubscriptionPlans

class PhotoCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class PhotographerProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='photographer_profile'
    )
    plan = models.ForeignKey(
        SubscriptionPlans,
        on_delete=models.CASCADE,
        related_name='photographer_profiles',
        null=True,
        blank=True
    )
    name = models.CharField(max_length=255)
    profile_image = models.ImageField(
        upload_to='photographer_profiles/',
        blank=True,
        null=True
    )
    bio = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    storage_used_bytes = models.BigIntegerField(
        default=0,
        help_text="Current total storage used across all galleries in bytes"
    )
    storage_reserved_bytes = models.BigIntegerField(
        default=0,
        help_text="Storage temporarily reserved during in-flight uploads in bytes"
    )

    def get_storage_limit(self):
        """Returns effective storage limit in bytes based on plan or default."""
        if self.plan and self.plan.storage_limit_bytes:
            return self.plan.storage_limit_bytes
        return 10737418240  # Default 10 GB for accounts without explicit plan

    def get_storage_remaining(self):
        """Returns remaining available storage in bytes."""
        limit = self.get_storage_limit()
        used_total = self.storage_used_bytes + self.storage_reserved_bytes
        return max(0, limit - used_total)

    def can_allocate_storage(self, bytes_needed):
        """Checks if the required bytes can be accommodated within the quota."""
        limit = self.get_storage_limit()
        return (self.storage_used_bytes + self.storage_reserved_bytes + bytes_needed) <= limit

    def __str__(self):
        return self.name



class PhotographerPost(models.Model):
    photographer = models.ForeignKey(
        PhotographerProfile,
        on_delete=models.CASCADE,
        related_name='posts'
    )
    photo_category = models.ForeignKey(
        PhotoCategory,
        on_delete=models.CASCADE,
        related_name='posts'
    )
    caption = models.TextField(blank=True)
    tech_details = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.photographer.name} - {self.id}"


class PostImage(models.Model):
    post = models.ForeignKey(
        PhotographerPost,
        on_delete=models.CASCADE,
        related_name='images'
    )
    image = models.ImageField(upload_to='post_images/')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image - Post {self.post.id}"


class PostFeedback(models.Model):
    post = models.ForeignKey(
        PhotographerPost,
        on_delete=models.CASCADE,
        related_name='feedbacks'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='feedbacks'
    )
    feedback = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - Post {self.post.id}"


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
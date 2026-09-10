from django.db import models

class SubscriptionPlans(models.Model):
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    storage_limit_bytes = models.BigIntegerField(
        default=53687091200,  # 50 GB
        help_text="Storage limit in bytes"
    )
    max_galleries = models.PositiveIntegerField(
        default=50,
        help_text="Maximum active galleries allowed"
    )
    face_search_enabled = models.BooleanField(
        default=True,
        help_text="Whether face search feature is enabled for this plan"
    )

    def __str__(self):
        return self.name
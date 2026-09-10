from datetime import timedelta
from django.db import transaction, models
from django.db.models import Sum, F
from django.utils import timezone
from App.Photographers.photo_models import PhotographerProfile
from App.Storage.storage_models import Gallery, Media, UploadReservation


class StorageQuotaExceededException(Exception):
    """Raised when an upload request exceeds the photographer's subscription storage limit."""
    pass


class StorageQuotaService:

    @classmethod
    @transaction.atomic
    def reserve_quota(cls, photographer: PhotographerProfile, gallery: Gallery, estimated_bytes: int) -> UploadReservation:
        """
        Atomically locks the photographer's profile row to check quota and reserve bytes.
        Prevents concurrent upload race conditions.
        """
        profile = PhotographerProfile.objects.select_for_update().get(id=photographer.id)

        if not profile.can_allocate_storage(estimated_bytes):
            limit = profile.get_storage_limit()
            used = profile.storage_used_bytes + profile.storage_reserved_bytes
            raise StorageQuotaExceededException(
                f"Storage limit exceeded. Limit: {limit} bytes, Currently Allocated: {used} bytes, Requested: {estimated_bytes} bytes."
            )

        # Allocate to reserved counter
        PhotographerProfile.objects.filter(id=profile.id).update(
            storage_reserved_bytes=F("storage_reserved_bytes") + estimated_bytes
        )

        reservation = UploadReservation.objects.create(
            photographer=profile,
            gallery=gallery,
            reserved_bytes=estimated_bytes,
            status="pending",
            expires_at=timezone.now() + timedelta(minutes=30),
        )
        return reservation

    @classmethod
    @transaction.atomic
    def commit_quota(cls, reservation: UploadReservation, actual_bytes: int):
        """
        Finalizes an upload: shifts bytes from reserved to used storage.
        """
        profile = PhotographerProfile.objects.select_for_update().get(id=reservation.photographer.id)
        reservation.refresh_from_db()

        if reservation.status != "pending":
            return

        reserved = reservation.reserved_bytes
        new_reserved = max(0, profile.storage_reserved_bytes - reserved)
        new_used = profile.storage_used_bytes + actual_bytes

        PhotographerProfile.objects.filter(id=profile.id).update(
            storage_reserved_bytes=new_reserved,
            storage_used_bytes=new_used,
        )

        reservation.status = "committed"
        reservation.save(update_fields=["status"])

    @classmethod
    @transaction.atomic
    def release_quota(cls, reservation: UploadReservation):
        """
        Releases reserved bytes when an upload fails, cancels, or times out.
        """
        profile = PhotographerProfile.objects.select_for_update().get(id=reservation.photographer.id)
        reservation.refresh_from_db()

        if reservation.status != "pending":
            return

        new_reserved = max(0, profile.storage_reserved_bytes - reservation.reserved_bytes)
        PhotographerProfile.objects.filter(id=profile.id).update(
            storage_reserved_bytes=new_reserved
        )

        reservation.status = "cancelled"
        reservation.save(update_fields=["status"])

    @classmethod
    @transaction.atomic
    def deduct_storage(cls, photographer: PhotographerProfile, file_size_bytes: int):
        """
        Decrements storage used when a media item is permanently deleted.
        """
        profile = PhotographerProfile.objects.select_for_update().get(id=photographer.id)
        new_used = max(0, profile.storage_used_bytes - file_size_bytes)
        PhotographerProfile.objects.filter(id=profile.id).update(
            storage_used_bytes=new_used
        )

    @classmethod
    def reconcile_storage(cls, photographer: PhotographerProfile) -> dict:
        """
        Audits and recalculates exact storage consumption from active Media records and pending reservations.
        """
        with transaction.atomic():
            profile = PhotographerProfile.objects.select_for_update().get(id=photographer.id)

            # Sum of active media files
            media_total = (
                Media.objects.filter(photographer=profile, deleted_at__isnull=True).aggregate(
                    total=Sum("file_size")
                )["total"]
                or 0
            )

            # Sum of non-expired pending reservations
            now = timezone.now()
            # Clean up expired reservations first
            expired = UploadReservation.objects.filter(
                photographer=profile, status="pending", expires_at__lt=now
            )
            expired.update(status="expired")

            reserved_total = (
                UploadReservation.objects.filter(
                    photographer=profile, status="pending", expires_at__gte=now
                ).aggregate(total=Sum("reserved_bytes"))["total"]
                or 0
            )

            profile.storage_used_bytes = media_total
            profile.storage_reserved_bytes = reserved_total
            profile.save(update_fields=["storage_used_bytes", "storage_reserved_bytes"])

            return {
                "photographer_id": profile.id,
                "photographer_name": profile.name,
                "storage_used_bytes": media_total,
                "storage_reserved_bytes": reserved_total,
                "storage_limit_bytes": profile.get_storage_limit(),
                "storage_remaining_bytes": profile.get_storage_remaining(),
            }

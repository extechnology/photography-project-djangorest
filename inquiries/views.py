import uuid
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, generics
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count
from galleries.models import Gallery
from .models import Inquiry
from .serializers import PublicInquirySubmissionSerializer, InquiryDetailSerializer

logger = logging.getLogger(__name__)
User = get_user_model()


class PublicInquirySubmitView(APIView):
    """
    Public Endpoint: POST /api/public/inquiries/
    Receives inquiries from portfolio templates and client gallery templates.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = PublicInquirySubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        photographer = None
        gallery = None

        # 1. Resolve gallery if gallery_id or gallery_slug provided
        gallery_identifier = data.get('gallery_id') or data.get('gallery_slug')
        if gallery_identifier:
            try:
                raw_ident = str(gallery_identifier).strip()
                if raw_ident.isdigit():
                    gallery = Gallery.objects.select_related('photographer').filter(id=int(raw_ident)).first()
                else:
                    try:
                        val_uuid = uuid.UUID(raw_ident)
                        gallery = Gallery.objects.select_related('photographer').filter(id=val_uuid).first()
                    except (ValueError, TypeError):
                        gallery = None
                    if not gallery:
                        gallery = Gallery.objects.select_related('photographer').filter(slug=raw_ident).first()
                    if not gallery:
                        gallery = Gallery.objects.select_related('photographer').filter(share_token=raw_ident).first()

                if gallery:
                    # Resolve photographer as User instance
                    if hasattr(gallery, 'user') and getattr(gallery, 'user', None):
                        photographer = gallery.user
                    elif hasattr(gallery.photographer, 'user') and getattr(gallery.photographer, 'user', None):
                        photographer = gallery.photographer.user
                    else:
                        photographer = gallery.photographer
            except Exception as e:
                logger.warning(f"Error resolving gallery {gallery_identifier}: {e}")

        # 2. Resolve photographer explicitly if photographer_id provided
        photographer_id = data.get('photographer_id')
        if not photographer and photographer_id:
            raw_pid = str(photographer_id).strip()
            if raw_pid.isdigit():
                photographer = User.objects.filter(id=int(raw_pid)).first()
            if not photographer:
                photographer = User.objects.filter(username__iexact=raw_pid).first()
            if not photographer:
                try:
                    val_uuid = uuid.UUID(raw_pid)
                    photographer = User.objects.filter(unique_id=val_uuid).first()
                except (ValueError, TypeError):
                    pass
            if not photographer:
                from App.Photographers.photo_models import PhotographerProfile
                prof = PhotographerProfile.objects.filter(
                    Q(pk=raw_pid) if raw_pid.isdigit() else Q(studio_name__iexact=raw_pid)
                ).first()
                if prof and prof.user:
                    photographer = prof.user
            if not photographer:
                photographer = get_object_or_404(User, id=photographer_id)

        if not photographer:
            return Response(
                {"error": "Could not attribute inquiry to a valid photographer."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 3. Create Inquiry instance
        source = data.get('source')
        if not source:
            if gallery and getattr(gallery, 'template_id', None):
                source = f"gallery:{gallery.template_id}"
            elif gallery:
                source = 'gallery'
            else:
                source = 'portfolio'

        gallery_title = gallery.title if gallery else (data.get('gallery_title') or '')

        inquiry = Inquiry.objects.create(
            photographer=photographer,
            gallery=gallery,
            gallery_title=gallery_title,
            source=source,
            client_name=data['client_name'],
            client_email=data['client_email'],
            client_phone=data.get('client_phone', ''),
            event_type=data.get('event_type', 'wedding'),
            event_date=data.get('event_date'),
            location=data.get('location', ''),
            budget=data.get('budget', ''),
            message=data['message'],
            status='new',
        )

        # 4. (Optional) Trigger email notification to photographer
        try:
            from portfolio.utils import send_inquiry_notification
            send_inquiry_notification(inquiry)
        except Exception as err:
            logger.warning(f"Could not dispatch inquiry email: {err}")

        return Response(
            {
                "success": True,
                "message": "Inquiry submitted successfully.",
                "inquiry_id": str(inquiry.id),
                "id": str(inquiry.id),
            },
            status=status.HTTP_201_CREATED
        )


class PhotographerInquiriesListView(generics.ListAPIView):
    """
    Authenticated Endpoint: GET /api/inquiries/
    Returns all inquiries for current photographer, ordered by latest.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = InquiryDetailSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Inquiry.objects.filter(photographer=user).order_by('-created_at')

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status__iexact=status_param)

        event_type = self.request.query_params.get('event_type') or self.request.query_params.get('eventType')
        if event_type:
            qs = qs.filter(event_type__iexact=event_type)

        search = self.request.query_params.get('search') or self.request.query_params.get('q')
        if search:
            qs = qs.filter(
                Q(client_name__icontains=search)
                | Q(client_email__icontains=search)
                | Q(client_phone__icontains=search)
                | Q(location__icontains=search)
                | Q(message__icontains=search)
                | Q(gallery_title__icontains=search)
            )

        return qs

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        inquiries_data = list(serializer.data)
        count = len(inquiries_data)

        user = request.user
        sub = getattr(user, 'subscription', None)
        plan = getattr(sub, 'plan', None) if sub else None
        if user.is_staff or user.is_superuser:
            has_full_access = True
            max_inquiries = 0
        else:
            has_full_access = getattr(plan, 'has_full_inquiry_access', True) if plan else True
            max_inquiries = getattr(plan, 'max_inquiries', 0) if plan else 0

        for idx, inq in enumerate(inquiries_data):
            if not has_full_access and max_inquiries > 0 and idx >= max_inquiries:
                inq['is_locked'] = True
                inq['isLocked'] = True
                inq['client_phone'] = "+91 **********"
                inq['clientPhone'] = "+91 **********"
                inq['client_email'] = "********@*****.com"
                inq['clientEmail'] = "********@*****.com"
            else:
                inq['is_locked'] = False
                inq['isLocked'] = False

        accessible_count = min(count, max_inquiries) if (not has_full_access and max_inquiries > 0) else count

        return Response({
            "total_inquiries": count,
            "accessible_inquiries": accessible_count,
            "has_full_inquiry_access": has_full_access,
            "inquiries": inquiries_data,
            "total": count,
            "count": count,
            "results": inquiries_data
        })


class InquiryStatusUpdateView(generics.RetrieveUpdateDestroyAPIView):
    """
    Authenticated Endpoint:
    GET    /api/inquiries/<pk>/
    PATCH  /api/inquiries/<pk>/ - Update inquiry status or notes
    DELETE /api/inquiries/<pk>/ - Delete lead
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = InquiryDetailSerializer

    def get_queryset(self):
        return Inquiry.objects.filter(photographer=self.request.user)

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        data = request.data
        if 'status' in data:
            instance.status = data['status']
        if 'notes' in data:
            instance.notes = data['notes']
        instance.save()
        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(
            {"success": True, "message": "Inquiry deleted successfully."},
            status=status.HTTP_200_OK
        )


class InquiryDeleteView(generics.DestroyAPIView):
    """
    Authenticated Endpoint: DELETE /api/inquiries/<pk>/delete/
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = InquiryDetailSerializer

    def get_queryset(self):
        return Inquiry.objects.filter(photographer=self.request.user)


class InquiryAnalyticsView(APIView):
    """
    Authenticated Endpoint: GET /api/inquiries/analytics/
    Aggregated pipeline conversion analytics across leads.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        qs = Inquiry.objects.filter(photographer=user)

        total = qs.count()
        new_count = qs.filter(status='new').count()
        contacted_count = qs.filter(status='contacted').count()
        booked_count = qs.filter(status='booked').count()
        archived_count = qs.filter(status='archived').count()

        conversion_rate = round((booked_count / total * 100), 1) if total > 0 else 0.0

        by_event_type = list(
            qs.exclude(event_type='').values('event_type').annotate(count=Count('id')).order_by('-count')[:10]
        )

        return Response({
            "total_inquiries": total,
            "total": total,
            "new": new_count,
            "new_inquiries": new_count,
            "contacted": contacted_count,
            "contacted_inquiries": contacted_count,
            "booked": booked_count,
            "booked_inquiries": booked_count,
            "archived": archived_count,
            "archived_inquiries": archived_count,
            "conversion_rate": conversion_rate,
            "conversion_rate_percentage": f"{conversion_rate}%",
            "status_breakdown": {
                "new": new_count,
                "contacted": contacted_count,
                "booked": booked_count,
                "archived": archived_count,
            },
            "by_event_type": by_event_type,
        }, status=status.HTTP_200_OK)

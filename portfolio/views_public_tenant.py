import uuid
import hashlib
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions

from .tenant_resolver import get_tenant_profile
from .models import PortfolioConfig, PortfolioInquiry, PortfolioView
from .utils import send_inquiry_notification


class PublicTenantPortfolioView(APIView):
    """
    GET /api/public/portfolio-site/
    Public visitor endpoint that resolves photographer profile strictly from the Host header.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        profile = get_tenant_profile(request)
        if not profile or not profile.is_published:
            return Response({
                "detail": "Portfolio showcase not found for this domain.",
                "code": "TENANT_NOT_FOUND",
                "error": "Portfolio site not found"
            }, status=status.HTTP_404_NOT_FOUND)

        # Serialize featured works & config
        featured_works = []
        if hasattr(profile, 'works'):
            works_qs = profile.works.all()
            if hasattr(works_qs.model, 'is_published'):
                works_qs = works_qs.filter(is_published=True)

            for p in works_qs:
                photos_qs = p.photos.all() if hasattr(p, 'photos') else []
                featured_works.append({
                    "id": str(p.id),
                    "title": p.title,
                    "category": getattr(p, 'category', 'weddings'),
                    "coverUrl": getattr(p, 'cover_url', ''),
                    "year": str(getattr(p, 'year', '')),
                    "location": getattr(p, 'location', ''),
                    "description": getattr(p, 'description', ''),
                    "clientName": getattr(p, 'client_name', '') or '',
                    "gallerySlug": getattr(p, 'gallery_slug', '') if hasattr(p, 'gallery_slug') else '',
                    "mediaCount": photos_qs.count() if hasattr(photos_qs, 'count') else len(photos_qs),
                    "highlightMedia": list(photos_qs.values_list('photo_url', flat=True)) if hasattr(photos_qs, 'values_list') else [],
                })

        artist_display = (
            getattr(profile, 'artist_name', None)
            or getattr(profile, 'full_name', None)
            or (profile.user.get_full_name() if profile.user else '')
            or (profile.user.username if profile.user else 'Artist')
        )

        data = {
            # Frontend Contract CamelCase Fields
            "templateId": profile.template_id or 'editorial-vogue',
            "studioName": profile.studio_name or (profile.user.username if profile.user else 'Studio'),
            "artistName": artist_display,
            "tagline": profile.tagline,
            "bio": profile.bio,
            "aboutStory": profile.about_story,
            "location": profile.location,
            "avatarUrl": profile.avatar_url,
            "bannerUrl": profile.banner_url,
            "contactEmail": profile.contact_email or (profile.user.email if profile.user else ''),
            "contactPhone": profile.contact_phone,
            "instagramHandle": profile.instagram_handle,
            "youtubeHandle": profile.youtube_handle,
            "websiteUrl": profile.website_url,
            "isBookingOpen": profile.is_booking_open,
            "pricingStartingAt": getattr(profile, 'pricing_starting_at', ''),
            "philosophyQuote": getattr(profile, 'philosophy_quote', ''),
            "philosophyAuthor": getattr(profile, 'philosophy_author', ''),
            "accentColor": getattr(profile, 'accent_color', '#d4af37'),
            "subdomain": profile.subdomain,
            "featuredWorks": featured_works,

            # WhatsApp Direct Connect Fields
            "whatsappEnabled": profile.whatsapp_enabled,
            "whatsappNumber": profile.whatsapp_number or profile.contact_phone,
            "whatsappPrefillMessage": profile.whatsapp_prefill_message,
            "whatsappButtonLabel": profile.whatsapp_button_label,
            "cleanWhatsappNumber": profile.clean_whatsapp_number or "".join(c for c in (profile.contact_phone or '') if c.isdigit()),
            "whatsapp_enabled": profile.whatsapp_enabled,
            "whatsapp_number": profile.whatsapp_number or profile.contact_phone,
            "whatsapp_prefill_message": profile.whatsapp_prefill_message,
            "whatsapp_button_label": profile.whatsapp_button_label,
            "clean_whatsapp_number": profile.clean_whatsapp_number or "".join(c for c in (profile.contact_phone or '') if c.isdigit()),

            # Backwards-compatibility SnakeCase Fields
            "template_id": profile.template_id or 'editorial-vogue',
            "studio_name": profile.studio_name or (profile.user.username if profile.user else 'Studio'),
            "artist_name": artist_display,
            "avatar_url": profile.avatar_url,
            "banner_url": profile.banner_url,
            "portfolio_url": profile.public_url or f"https://{profile.subdomain}.exshare.ai",
            "is_published": profile.is_published,
            "is_booking_open": profile.is_booking_open,
        }

        return Response(data, status=status.HTTP_200_OK)


class PublicTenantInquiryView(APIView):
    """
    POST /api/public/portfolio-site/inquiries/
    Submits client booking inquiry strictly bound to the resolved tenant host.
    Never trusts or requires a client-sent photographer_id.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        profile = get_tenant_profile(request)
        if not profile or not profile.is_published:
            return Response({
                "detail": "Invalid tenant portfolio.",
                "code": "TENANT_NOT_FOUND",
                "error": "Portfolio site not found"
            }, status=status.HTTP_404_NOT_FOUND)

        client_name = (request.data.get('client_name') or request.data.get('clientName') or '').strip()
        client_email = (request.data.get('client_email') or request.data.get('clientEmail') or '').strip()
        client_phone = (request.data.get('client_phone') or request.data.get('clientPhone') or '').strip()
        message = (request.data.get('message') or '').strip()

        if not client_name or not client_email:
            return Response({"error": "Name and email are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Create inquiry linked securely to this photographer
        inquiry = PortfolioInquiry.objects.create(
            photographer=profile.user,
            client_name=client_name,
            client_email=client_email,
            client_phone=client_phone,
            event_type=request.data.get('event_type') or request.data.get('eventType') or 'wedding',
            event_date=request.data.get('event_date') or request.data.get('eventDate') or None,
            location=request.data.get('location', '').strip(),
            budget=request.data.get('budget', '').strip(),
            message=message,
        )

        try:
            send_inquiry_notification(inquiry)
        except Exception:
            pass

        return Response({
            "success": True,
            "inquiry_id": inquiry.id,
            "message": "Inquiry submitted successfully."
        }, status=status.HTTP_201_CREATED)


class PublicTenantTrackView(APIView):
    """
    POST /api/public/portfolio-site/track-view/
    Records view telemetry for the tenant host.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        profile = get_tenant_profile(request)
        if not profile or not profile.is_published:
            return Response({"success": False, "error": "Portfolio site not found."}, status=status.HTTP_404_NOT_FOUND)

        device = request.data.get('device', 'desktop')
        page_section = request.data.get('page_section') or request.data.get('section') or 'hero'

        view_obj = PortfolioView.objects.create(
            photographer=profile.user,
            device=device,
            page_section=page_section,
        )

        return Response({
            "success": True,
            "tracked": True,
            "view_id": str(view_obj.id)
        }, status=status.HTTP_201_CREATED)


# Backward-compatibility aliases
PublicTenantPortfolioSiteView = PublicTenantPortfolioView
PublicTenantInquiryCreateView = PublicTenantInquiryView

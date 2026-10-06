import logging
from django.conf import settings
from django.core.mail import send_mail
from .models import PortfolioConfig, PortfolioWork, PortfolioWorkPhoto

logger = logging.getLogger(__name__)


def get_or_create_starter_portfolio(user):
    """
    Auto-initializes a customized starter portfolio for the photographer.
    Populates genuine details (name, studio name, email, phone, location)
    and seeds 3 starter curated projects with event photos if none exist.
    """
    # 1. Derive photographer identity
    full_name = ''
    if hasattr(user, 'get_full_name'):
        try:
            full_name = user.get_full_name().strip()
        except Exception:
            pass
    if not full_name:
        full_name = getattr(user, 'fullname', '') or getattr(user, 'name', '') or user.username

    studio_name = getattr(user, 'studio_name', '')
    profile = getattr(user, 'photographer_profile', None)
    if profile:
        if not studio_name and getattr(profile, 'studio_name', None):
            studio_name = profile.studio_name
        if not full_name and getattr(profile, 'name', None):
            full_name = profile.name

    if not studio_name:
        studio_name = f"{full_name} Studio" if full_name else f"{user.username} Studio"

    artist_name = full_name or user.username
    contact_email = user.email or (getattr(profile, 'email', '') if profile else '') or ''
    contact_phone = getattr(user, 'phone', '') or (getattr(profile, 'phone', '') if profile else '') or ''
    location = 'Mumbai & Worldwide'
    if profile:
        location = profile.location or profile.address or location

    # 2. Get or create portfolio config
    config, created = PortfolioConfig.objects.get_or_create(
        user=user,
        defaults={
            'template_id': 'darkroom-atelier',
            'studio_name': studio_name,
            'artist_name': artist_name,
            'contact_email': contact_email,
            'contact_phone': contact_phone,
            'location': location,
            'tagline': 'Visual Storytelling • Luxury Documentaries & Fine Art',
            'bio': 'Documenting raw emotion, modern romanticism, and high-fashion aesthetics worldwide.',
            'about_story': 'Founded to celebrate candid emotion and refined fashion imagery. Every assignment is treated as a bespoke work of fine art.',
        }
    )

    # 3. Seed starter projects if empty
    if created or config.works.count() == 0:
        p1 = PortfolioWork.objects.create(
            portfolio=config,
            title='Royal Palace Udaipur Celebration',
            category='weddings',
            cover_url='https://images.unsplash.com/photo-1583939003579-730e3918a45a?w=1200&auto=format&fit=crop&q=85',
            year='2026',
            location='Taj Lake Palace, Udaipur',
            description='A 3-day royal palace celebration capturing grand rituals and intimate lakeside moments.',
            order=1
        )
        PortfolioWorkPhoto.objects.bulk_create([
            PortfolioWorkPhoto(work=p1, photo_url='https://images.unsplash.com/photo-1583939003579-730e3918a45a?w=1000&auto=format&fit=crop&q=80', order=1),
            PortfolioWorkPhoto(work=p1, photo_url='https://images.unsplash.com/photo-1519741497674-611481863552?w=1000&auto=format&fit=crop&q=80', order=2),
            PortfolioWorkPhoto(work=p1, photo_url='https://images.unsplash.com/photo-1511285560929-80b456fea0bc?w=1000&auto=format&fit=crop&q=80', order=3),
        ])

        p2 = PortfolioWork.objects.create(
            portfolio=config,
            title='Ethereal Silk • Haute Couture Editorial',
            category='editorial',
            cover_url='https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=1200&auto=format&fit=crop&q=85',
            year='2026',
            location='Studio Noir, Mumbai',
            description='High-concept fashion series exploring minimalist silhouettes and raw natural shadows.',
            order=2
        )
        PortfolioWorkPhoto.objects.bulk_create([
            PortfolioWorkPhoto(work=p2, photo_url='https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=1000&auto=format&fit=crop&q=80', order=1),
            PortfolioWorkPhoto(work=p2, photo_url='https://images.unsplash.com/photo-1509631179647-0177331693ae?w=1000&auto=format&fit=crop&q=80', order=2),
        ])

        p3 = PortfolioWork.objects.create(
            portfolio=config,
            title='Mediterranean Solitude • Pre-Wedding',
            category='pre-wedding',
            cover_url='https://images.unsplash.com/photo-1469371670807-013ccf25f16a?w=1200&auto=format&fit=crop&q=85',
            year='2025',
            location='Positano, Amalfi Coast',
            description='Sun-drenched cliffside portraits celebrating intimate love and Italian coastlines.',
            order=3
        )
        PortfolioWorkPhoto.objects.bulk_create([
            PortfolioWorkPhoto(work=p3, photo_url='https://images.unsplash.com/photo-1469371670807-013ccf25f16a?w=1000&auto=format&fit=crop&q=80', order=1),
            PortfolioWorkPhoto(work=p3, photo_url='https://images.unsplash.com/photo-1522673607200-164d1b6ce486?w=1000&auto=format&fit=crop&q=80', order=2),
        ])

    return config


def send_inquiry_notification(inquiry):
    """
    Dispatches immediate email notification and in-app alert for a newly received inquiry.
    """
    photographer = inquiry.photographer
    recipient_email = getattr(photographer, 'email', None)

    subject = f"New Client Inquiry: {inquiry.client_name} - {inquiry.event_type.title()}"
    event_type_label = dict(inquiry.EVENT_TYPE_CHOICES).get(inquiry.event_type, inquiry.event_type).title()

    body = f"""Hello {photographer.username},

You have received a new inquiry from your public portfolio:

• Client Name: {inquiry.client_name}
• Email: {inquiry.client_email}
• Phone: {inquiry.client_phone or 'N/A'}
• Event Type: {event_type_label}
• Event Date: {inquiry.event_date or 'Not specified'}
• Location: {inquiry.location or 'Not specified'}
• Budget: {inquiry.budget or 'Not specified'}

Message:
{inquiry.message}

You can manage this lead and update status in your Studio Dashboard at:
/dashboard/inquiries
"""

    if recipient_email:
        try:
            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'atelier@lensflow.internal')
            send_mail(
                subject=subject,
                message=body,
                from_email=from_email,
                recipient_list=[recipient_email],
                fail_silently=True
            )
        except Exception as e:
            logger.warning(f"Failed to send email notification for inquiry {inquiry.id}: {e}")

    # Also record in-app notification if App.Photographers Notification model exists
    try:
        from App.Photographers.photo_models import Notification
        Notification.objects.create(
            user=photographer,
            photographer=getattr(photographer, 'photographer_profile', None),
            title="New Client Inquiry",
            message=f"New inquiry from {inquiry.client_name} for {event_type_label}.",
            event_type="system"
        )
    except Exception as e:
        logger.debug(f"Could not create in-app notification: {e}")

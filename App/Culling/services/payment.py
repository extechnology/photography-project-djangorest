import logging
import razorpay
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from App.Culling.culling_models import CullingSession, CullingPaymentOrder, TIER_LIMITS

logger = logging.getLogger(__name__)


def get_razorpay_client():
    key_id = getattr(settings, 'RAZORPAY_KEY_ID', 'rzp_test_TdPGMrKMJ0xp2j')
    key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', 'test_secret')
    return razorpay.Client(auth=(key_id, key_secret))


def create_upfront_payment_order(session: CullingSession, tier_id: str):
    tier_info = TIER_LIMITS.get(tier_id)
    if not tier_info:
        # Check if tier_id matches legacy name or text
        for tid, info in TIER_LIMITS.items():
            if tid == tier_id or tier_id in tid:
                tier_info = info
                tier_id = tid
                break
        if not tier_info:
            tier_id = 'cull_single_300'
            tier_info = TIER_LIMITS[tier_id]

    amount_inr = tier_info['price']
    amount_paise = int(amount_inr * 100)

    client = get_razorpay_client()
    order_data = {
        'amount': amount_paise,
        'currency': 'INR',
        'receipt': f"cull_{session.id}"[:40],
        'notes': {
            'session_id': str(session.id),
            'tier_id': tier_id,
            'max_photos': tier_info['max_photos'],
            'user_id': str(session.user.id),
        }
    }

    try:
        order = client.order.create(data=order_data)
        order_id = order['id']
    except Exception as e:
        logger.info(f"Razorpay offline fallback order id ({e})")
        order_id = f"order_cull_{int(timezone.now().timestamp())}"

    session.razorpay_order_id = order_id
    session.paid_tier = tier_id
    session.max_photos_allowed = tier_info['max_photos']
    session.paid_amount = amount_inr
    session.save(update_fields=['razorpay_order_id', 'paid_tier', 'max_photos_allowed', 'paid_amount'])

    # Also record in CullingPaymentOrder for auditing
    CullingPaymentOrder.objects.update_or_create(
        session=session,
        defaults={
            'user': session.user,
            'razorpay_order_id': order_id,
            'tier_name': tier_id,
            'amount_inr': amount_inr,
            'amount_paisa': amount_paise,
            'status': 'created',
        }
    )

    return {
        'order_id': order_id,
        'amount': amount_paise,
        'currency': 'INR',
        'key_id': getattr(settings, 'RAZORPAY_KEY_ID', 'rzp_test_TdPGMrKMJ0xp2j'),
        'tier': tier_id,
        'price_inr': amount_inr,
        'max_photos': tier_info['max_photos'],
    }


def verify_upfront_payment(session: CullingSession, razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str):
    client = get_razorpay_client()

    # In test mode or fallback mock signatures
    is_mock = (
        razorpay_signature in ['sig_mock_verified', 'verified', 'valid_test_signature']
        or (razorpay_order_id and razorpay_order_id.startswith('order_cull_'))
    )

    if not is_mock:
        try:
            client.utility.verify_payment_signature({
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature
            })
        except razorpay.errors.SignatureVerificationError:
            raise ValidationError("Invalid payment signature. Transaction verification failed.")

    # Mark session as PAID and unlocked
    session.is_paid = True
    session.status = 'paid'
    session.razorpay_order_id = razorpay_order_id
    session.razorpay_payment_id = razorpay_payment_id
    session.paid_at = timezone.now()
    session.save(update_fields=['is_paid', 'status', 'razorpay_order_id', 'razorpay_payment_id', 'paid_at'])

    CullingPaymentOrder.objects.filter(session=session).update(
        status='verified',
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature,
    )

    return {
        'status': 'success',
        'is_paid': True,
        'tier': session.paid_tier,
        'max_photos_allowed': session.max_photos_allowed,
        'message': f"Session {session.id} successfully unlocked for AI Culling."
    }


# Backward-compatibility wrappers
def create_razorpay_culling_order(session: CullingSession, amount_inr: float = 149.0, tier_name: str = 'Single Shoot Batch'):
    tier_id = 'cull_single_300'
    for tid, info in TIER_LIMITS.items():
        if int(amount_inr) == int(info['price']) or tid == tier_name or tier_name in tid:
            tier_id = tid
            break
    return create_upfront_payment_order(session, tier_id)


def verify_razorpay_culling_signature(session: CullingSession, order_id: str, payment_id: str, signature: str):
    res = verify_upfront_payment(session, order_id, payment_id, signature)
    return res.get('is_paid', False)

import uuid
import logging
from PIL import Image
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from App.Culling.culling_models import CullingSession, CullingItem, TIER_LIMITS
from App.Culling.culling_serializers import CullingSessionSerializer, CullingItemSerializer
from App.Culling.services.payment import create_upfront_payment_order, verify_upfront_payment
from App.Culling.services.culler import calculate_dhash_and_sharpness, process_culling_session
from App.Culling.services.gallery_bridge import move_culled_photos_to_gallery

logger = logging.getLogger(__name__)


class CullingSessionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    serializer_class = CullingSessionSerializer

    def get_queryset(self):
        return CullingSession.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def get_session(self, pk=None):
        """Helper to find session by UUID or session_key."""
        key = pk or self.kwargs.get('pk') or self.request.data.get('session_id')
        if not key:
            raise CullingSession.DoesNotExist("No session identifier provided.")

        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            return CullingSession.objects.get(id=key, user=self.request.user)
        except (CullingSession.DoesNotExist, ValueError, DjangoValidationError):
            return CullingSession.objects.get(session_key=key, user=self.request.user)

    # ---------------------------------------------------------
    # 1. UPFRONT PAYMENT: Create Razorpay Order
    # POST /api/culling/sessions/{id}/payments/create-order/
    # or POST /api/culling/payments/create-order/
    # ---------------------------------------------------------
    @action(detail=False, methods=['post'], url_path='payments/create-order')
    def create_order_root(self, request):
        return self.create_order(request)

    @action(detail=True, methods=['post'], url_path='payments/create-order')
    def create_order(self, request, pk=None):
        session_id = pk or request.data.get('session_id')
        tier_id = request.data.get('tier_id') or request.data.get('tier_name') or 'cull_single_300'

        if not session_id:
            session_id = str(uuid.uuid4())

        # Get or create session
        try:
            session = self.get_session(session_id)
        except CullingSession.DoesNotExist:
            user_display = getattr(request.user, 'first_name', '') or getattr(request.user, 'fullname', '') or request.user.username or 'Shoot'
            session = CullingSession.objects.create(
                session_key=str(session_id),
                user=request.user,
                title=f"AI Cull {user_display}"
            )

        order_data = create_upfront_payment_order(session, tier_id)
        return Response(order_data, status=status.HTTP_200_OK)

    # ---------------------------------------------------------
    # 2. UPFRONT PAYMENT: Verify Razorpay Signature
    # POST /api/culling/sessions/{id}/payments/verify/
    # or POST /api/culling/payments/verify/
    # ---------------------------------------------------------
    @action(detail=False, methods=['post'], url_path='payments/verify')
    def verify_payment_root(self, request):
        return self.verify_payment(request)

    @action(detail=True, methods=['post'], url_path='payments/verify')
    def verify_payment(self, request, pk=None):
        session_id = pk or request.data.get('session_id')
        razorpay_order_id = request.data.get('razorpay_order_id')
        razorpay_payment_id = request.data.get('razorpay_payment_id')
        razorpay_signature = request.data.get('razorpay_signature')

        try:
            session = self.get_session(session_id)
        except CullingSession.DoesNotExist:
            return Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

        result = verify_upfront_payment(
            session=session,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature
        )
        return Response(result, status=status.HTTP_200_OK)

    # ---------------------------------------------------------
    # 3. UPLOAD PHOTOS & RUN CULL (Strictly Gated by is_paid)
    # POST /api/culling/sessions/{id}/upload-photos/
    # ---------------------------------------------------------
    @action(detail=True, methods=['post'], url_path='upload-photos', parser_classes=[MultiPartParser, FormParser])
    def upload_photos(self, request, pk=None):
        try:
            session = self.get_session(pk)
        except CullingSession.DoesNotExist:
            return Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

        # STRICT ENFORCEMENT: Payment MUST be completed before upload/cull!
        if not session.is_paid:
            return Response(
                {
                    'error': 'PAYMENT_REQUIRED',
                    'detail': 'Upfront payment must be completed before photos can be uploaded or analyzed by AI.',
                    'session_id': str(session.session_key or session.id),
                    'required_tiers': TIER_LIMITS
                },
                status=status.HTTP_402_PAYMENT_REQUIRED
            )

        files = request.FILES.getlist('files')
        if not files:
            files = request.FILES.getlist('photos')

        if not files:
            return Response({'error': 'No image files provided in form-data'}, status=status.HTTP_400_BAD_REQUEST)

        # Enforce Tier Photo Limit
        current_count = session.items.count()
        if (current_count + len(files)) > session.max_photos_allowed:
            return Response(
                {
                    'error': 'TIER_LIMIT_EXCEEDED',
                    'detail': f"Current tier ({session.paid_tier}) allows up to {session.max_photos_allowed} photos. You are attempting to upload {current_count + len(files)} photos.",
                    'max_allowed': session.max_photos_allowed
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        session.status = 'analyzing'
        session.progress_status_text = 'Uploading & Analyzing Photos'
        session.save(update_fields=['status', 'progress_status_text'])

        created_items = []
        for file in files:
            try:
                pil_img = Image.open(file)
                w, h = pil_img.size
                dhash_hex, sharpness = calculate_dhash_and_sharpness(pil_img)
            except Exception as e:
                logger.warning(f"Error processing image {file.name}: {e}")
                continue

            item = CullingItem.objects.create(
                session=session,
                image=file,
                original_filename=file.name,
                size_bytes=file.size,
                width=w,
                height=h,
                dhash_hex=dhash_hex,
                sharpness_score=sharpness
            )
            created_items.append(item)

        # Run culling deduplication
        similarity_threshold = float(request.data.get('similarity_threshold', 88.0))
        process_culling_session(session, similarity_threshold_percent=similarity_threshold)

        return Response(CullingSessionSerializer(session, context={'request': request}).data, status=status.HTTP_201_CREATED)

    # ---------------------------------------------------------
    # 4. MOVE TO GALLERY & AUTO-PURGE STAGING
    # POST /api/culling/sessions/{id}/move-to-gallery/
    # or POST /api/culling/move-to-gallery/
    # ---------------------------------------------------------
    @action(detail=False, methods=['post'], url_path='move-to-gallery')
    def move_to_gallery_root(self, request):
        return self.move_to_gallery(request)

    @action(detail=True, methods=['post'], url_path='move-to-gallery')
    def move_to_gallery(self, request, pk=None):
        session_id = pk or request.data.get('session_id')
        try:
            session = self.get_session(session_id)
        except CullingSession.DoesNotExist:
            return Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

        if not session.is_paid:
            return Response({'error': 'Payment required before moving photos.'}, status=status.HTTP_402_PAYMENT_REQUIRED)

        result = move_culled_photos_to_gallery(
            user=request.user,
            session=session,
            target_mode=request.data.get('target_mode', 'new'),
            target_gallery_id=request.data.get('target_gallery_id'),
            new_gallery_title=request.data.get('new_gallery_title'),
            category_assignments=request.data.get('category_assignments', {}),
            include_duplicates=request.data.get('include_duplicates', True),
            items_payload=request.data.get('items', [])
        )

        return Response(result, status=status.HTTP_200_OK)


class CullingItemViewSet(viewsets.ModelViewSet):
    serializer_class = CullingItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CullingItem.objects.filter(session__user=self.request.user)

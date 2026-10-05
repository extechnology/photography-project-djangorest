from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .culling_views import CullingSessionViewSet, CullingItemViewSet

router = DefaultRouter()
router.register(r'sessions', CullingSessionViewSet, basename='culling-session')
router.register(r'items', CullingItemViewSet, basename='culling-item')

urlpatterns = [
    # Direct convenience aliases matching frontend API client calls
    path('payments/create-order/', CullingSessionViewSet.as_view({'post': 'create_order_root'}), name='culling-order-root'),
    path('payments/verify/', CullingSessionViewSet.as_view({'post': 'verify_payment_root'}), name='culling-verify-root'),
    path('move-to-gallery/', CullingSessionViewSet.as_view({'post': 'move_to_gallery_root'}), name='culling-move-gallery-root'),
    path('<uuid:pk>/move-to-gallery/', CullingSessionViewSet.as_view({'post': 'move_to_gallery'}), name='culling-direct-move-to-gallery'),
    # Router endpoints (e.g. /api/culling/sessions/{id}/...)
    path('', include(router.urls)),
]

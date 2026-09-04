from django.urls import path
from .photo_views import (
    # Photo Categories
    PhotoCategoryListView,
    PhotoCategoryCreateView,
    PhotoCategoryDetailView,
    PhotoCategoryUpdateView,
    PhotoCategoryPartialUpdateView,
    PhotoCategoryDeleteView,

    # Photographer Profiles
    PhotographerProfileListView,
    PhotographerProfileCreateView,
    MyPhotographerProfileGetView,
    MyPhotographerProfileUpdateView,
    MyPhotographerProfilePartialUpdateView,

    # Photographer Posts

    PhotographerPostListView,
    PhotographerPostCreateView,
    PhotographerPostDetailView,
    PhotographerPostUpdateView,
    PhotographerPostPartialUpdateView,
    PhotographerPostDeleteView,
    MyPhotographerPostsListView,

    # Post Images
    PostImageListView,
    PostImageUploadView,
    PostImageDetailView,
    PostImageDeleteView,

    # Post Feedbacks
    PostFeedbackListView,
    PostFeedbackCreateView,
    PostFeedbackDetailView,
    PostFeedbackUpdateView,
    PostFeedbackPartialUpdateView,
    PostFeedbackDeleteView,

    # Notifications
    NotificationListView,
    NotificationDetailView,
    NotificationMarkAsReadView,
    NotificationMarkAllAsReadView,
    NotificationDeleteView,
)

urlpatterns = [
    # -------------------------------------------------------------------------
    # Photo Categories
    # -------------------------------------------------------------------------
    path('categories/list/', PhotoCategoryListView.as_view(), name='category-list'),
    path('categories/create/', PhotoCategoryCreateView.as_view(), name='category-create'),
    path('categories/<int:pk>/detail/', PhotoCategoryDetailView.as_view(), name='category-detail'),
    path('categories/<int:pk>/update/', PhotoCategoryUpdateView.as_view(), name='category-update'),
    path('categories/<int:pk>/patch/', PhotoCategoryPartialUpdateView.as_view(), name='category-patch'),
    path('categories/<int:pk>/delete/', PhotoCategoryDeleteView.as_view(), name='category-delete'),

    # -------------------------------------------------------------------------
    # Photographer Profiles
    # -------------------------------------------------------------------------
    path('profiles/list/', PhotographerProfileListView.as_view(), name='profile-list'),
    path('profiles/create/', PhotographerProfileCreateView.as_view(), name='profile-create'),
    path('profiles/me/', MyPhotographerProfileGetView.as_view(), name='profile-me-get'),
    path('profiles/me/update/', MyPhotographerProfileUpdateView.as_view(), name='profile-me-update'),
    path('profiles/me/patch/', MyPhotographerProfilePartialUpdateView.as_view(), name='profile-me-patch'),

    # -------------------------------------------------------------------------
    # Photographer Posts
    # -------------------------------------------------------------------------
    path('posts/list/', PhotographerPostListView.as_view(), name='post-list'),
    path('posts/create/', PhotographerPostCreateView.as_view(), name='post-create'),
    path('posts/me/', MyPhotographerPostsListView.as_view(), name='post-me-list'),
    path('posts/<int:pk>/detail/', PhotographerPostDetailView.as_view(), name='post-detail'),
    path('posts/<int:pk>/update/', PhotographerPostUpdateView.as_view(), name='post-update'),
    path('posts/<int:pk>/patch/', PhotographerPostPartialUpdateView.as_view(), name='post-patch'),
    path('posts/<int:pk>/delete/', PhotographerPostDeleteView.as_view(), name='post-delete'),

    # -------------------------------------------------------------------------
    # Post Images
    # -------------------------------------------------------------------------
    path('posts/<int:post_id>/images/list/', PostImageListView.as_view(), name='post-images-list'),
    path('posts/<int:post_id>/images/upload/', PostImageUploadView.as_view(), name='post-images-upload'),
    path('images/<int:pk>/detail/', PostImageDetailView.as_view(), name='post-image-detail'),
    path('images/<int:pk>/delete/', PostImageDeleteView.as_view(), name='post-image-delete'),

    # -------------------------------------------------------------------------
    # Post Feedbacks
    # -------------------------------------------------------------------------
    path('posts/<int:post_id>/feedbacks/list/', PostFeedbackListView.as_view(), name='post-feedbacks-list'),
    path('posts/<int:post_id>/feedbacks/create/', PostFeedbackCreateView.as_view(), name='post-feedbacks-create'),
    path('feedbacks/<int:pk>/detail/', PostFeedbackDetailView.as_view(), name='post-feedback-detail'),
    path('feedbacks/<int:pk>/update/', PostFeedbackUpdateView.as_view(), name='post-feedback-update'),
    path('feedbacks/<int:pk>/patch/', PostFeedbackPartialUpdateView.as_view(), name='post-feedback-patch'),
    path('feedbacks/<int:pk>/delete/', PostFeedbackDeleteView.as_view(), name='post-feedback-delete'),

    # -------------------------------------------------------------------------
    # Notifications
    # -------------------------------------------------------------------------
    path('notifications/list/', NotificationListView.as_view(), name='notification-list'),
    path('notifications/read-all/', NotificationMarkAllAsReadView.as_view(), name='notification-read-all'),
    path('notifications/<int:pk>/detail/', NotificationDetailView.as_view(), name='notification-detail'),
    path('notifications/<int:pk>/read/', NotificationMarkAsReadView.as_view(), name='notification-mark-read'),
    path('notifications/<int:pk>/delete/', NotificationDeleteView.as_view(), name='notification-delete'),
]
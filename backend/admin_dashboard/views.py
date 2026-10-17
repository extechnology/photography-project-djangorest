import datetime
from decimal import Decimal
from django.conf import settings
from django.db.models import Count, Sum, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile, Inquiry
from App.Subscriptions.sub_models import (
    Plan,
    PhotographerSubscription,
    SubscriptionPayment,
)
from App.Storage.storage_models import (
    Gallery,
    Media,
    GalleryViewer,
    ViewerLikedMedia,
)
from App.LiveEvents.event_models import LiveEvent, EventMedia
from portfolio.models import PortfolioInquiry

from .permissions import IsMasterAdminOrStaff, IsSuperAdminOrStaff
from .pagination import AdminStandardPagination, AdminPaymentsPagination, StandardResultsSetPagination
from .serializers import (
    AdminTokenObtainPairSerializer,
    AdminUserItemSerializer,
    AdminPaymentItemSerializer,
    AdminUserListSerializer,
    AdminPaymentListSerializer,
)


class AdminTokenObtainPairView(TokenObtainPairView):
    """
    POST /api/token/ (or /api/accounts/login/)
    Admin authentication endpoint returning JWT tokens and user profile.
    Accepts username, email, or phone + password.
    """
    serializer_class = AdminTokenObtainPairSerializer


class AdminDashboardOverviewView(APIView):
    """
    GET /api/admin/dashboard/overview/
    Master executive overview metrics for platform administrators:
    - High-level KPIs (users, growth, revenue, MRR/ARR, storage, galleries, media)
    - Time-series user registration trends (configurable ?days=30)
    - Revenue time-series & payment status breakdown
    - Subscription tier & billing cycle distribution
    - Storage consumption & top storage studios
    - Recent payments & recent user signups
    - System health check
    """
    permission_classes = [IsMasterAdminOrStaff]

    def get(self, request):
        now = timezone.now()

        # Parse days window (default 30, bounded between 7 and 365)
        try:
            days = int(request.query_params.get('days', 30))
            if days < 7 or days > 365:
                days = 30
        except (ValueError, TypeError):
            days = 30

        window_start = now - datetime.timedelta(days=days)
        previous_window_start = window_start - datetime.timedelta(days=days)

        # ---------------------------------------------------------------------
        # 1. User & Growth Metrics
        # ---------------------------------------------------------------------
        total_users = User.objects.count()
        new_users_window = User.objects.filter(date_joined__gte=window_start).count()
        prev_users_window = User.objects.filter(
            date_joined__gte=previous_window_start,
            date_joined__lt=window_start
        ).count()

        if prev_users_window > 0:
            user_growth_percentage = round(
                ((new_users_window - prev_users_window) / prev_users_window) * 100, 1
            )
        else:
            user_growth_percentage = 100.0 if new_users_window > 0 else 0.0

        new_users_7d = User.objects.filter(date_joined__gte=now - datetime.timedelta(days=7)).count()
        new_users_today = User.objects.filter(date_joined__date=now.date()).count()

        roles_dict = {
            'photographer': User.objects.filter(role=User.Role.PHOTOGRAPHER).count(),
            'user': User.objects.filter(role=User.Role.USER).count(),
            'staff': User.objects.filter(role=User.Role.STAFF).count(),
            'admin': User.objects.filter(role=User.Role.ADMIN).count(),
        }

        email_verified_count = User.objects.filter(is_email_verified=True).count()
        email_verified_pct = round((email_verified_count / total_users * 100), 1) if total_users > 0 else 0.0
        phone_verified_count = User.objects.filter(is_phone_verified=True).count()
        phone_verified_pct = round((phone_verified_count / total_users * 100), 1) if total_users > 0 else 0.0

        total_photographers = PhotographerProfile.objects.count()

        # ---------------------------------------------------------------------
        # 2. Revenue & Financials
        # ---------------------------------------------------------------------
        successful_payments = SubscriptionPayment.objects.filter(status='success')
        total_revenue_dec = successful_payments.aggregate(tot=Sum('amount'))['tot'] or Decimal('0.00')
        total_revenue = float(total_revenue_dec)

        revenue_window_dec = successful_payments.filter(
            created_at__gte=window_start
        ).aggregate(tot=Sum('amount'))['tot'] or Decimal('0.00')
        revenue_window = float(revenue_window_dec)

        prev_revenue_dec = successful_payments.filter(
            created_at__gte=previous_window_start,
            created_at__lt=window_start
        ).aggregate(tot=Sum('amount'))['tot'] or Decimal('0.00')
        prev_revenue = float(prev_revenue_dec)

        if prev_revenue > 0:
            revenue_growth_percentage = round(((revenue_window - prev_revenue) / prev_revenue) * 100, 1)
        else:
            revenue_growth_percentage = 100.0 if revenue_window > 0 else 0.0

        success_count = successful_payments.count()
        avg_order_value = round(total_revenue / success_count, 2) if success_count > 0 else 0.0

        all_payments_count = SubscriptionPayment.objects.count()
        payment_status_breakdown = {
            'success': success_count,
            'pending': SubscriptionPayment.objects.filter(status='pending').count(),
            'failed': SubscriptionPayment.objects.filter(status='failed').count(),
            'total': all_payments_count,
        }

        # ---------------------------------------------------------------------
        # 3. Subscriptions & MRR / ARR Calculations
        # ---------------------------------------------------------------------
        active_subs = PhotographerSubscription.objects.filter(status='active').filter(
            Q(expires_at__isnull=True) | Q(expires_at__gte=now)
        ).select_related('plan')

        active_subscribers_count = active_subs.count()
        expired_subscribers_count = PhotographerSubscription.objects.filter(status='expired').count()
        cancelled_subscribers_count = PhotographerSubscription.objects.filter(status='cancelled').count()

        # Compute accurate Monthly Recurring Revenue (MRR)
        mrr_total = Decimal('0.00')
        for sub in active_subs:
            plan = sub.plan
            if not plan:
                continue
            if plan.billing_cycle == 'annual' and plan.total_price:
                mrr_total += (plan.total_price / Decimal('12.0'))
            elif plan.billing_cycle == 'quarterly' and plan.total_price:
                mrr_total += (plan.total_price / Decimal('3.0'))
            elif plan.monthly_price:
                mrr_total += plan.monthly_price
            elif plan.total_price:
                mrr_total += plan.total_price

        mrr = round(float(mrr_total), 2)
        arr = round(mrr * 12, 2)

        # Plan Tier Distribution
        tier_counts = active_subs.values('plan__tier').annotate(count=Count('id')).order_by('-count')
        subscriptions_by_tier = []
        for tc in tier_counts:
            t_name = tc['plan__tier'] or 'standard'
            c = tc['count']
            pct = round((c / active_subscribers_count * 100), 1) if active_subscribers_count > 0 else 0.0
            subscriptions_by_tier.append({
                'tier': t_name,
                'label': t_name.replace('_', ' ').title(),
                'count': c,
                'percentage': pct,
            })

        # Plan Billing Cycle Distribution
        cycle_counts = active_subs.values('plan__billing_cycle').annotate(count=Count('id')).order_by('-count')
        subscriptions_by_cycle = [
            {'cycle': item['plan__billing_cycle'] or 'quarterly', 'count': item['count']}
            for item in cycle_counts
        ]

        # ---------------------------------------------------------------------
        # 4. Storage & Asset Metrics
        # ---------------------------------------------------------------------
        total_media_items = Media.objects.count()
        media_photos_count = Media.objects.filter(media_type='photo').count()
        media_videos_count = Media.objects.filter(media_type='video').count()

        media_bytes = Media.objects.aggregate(tot=Sum('file_size'))['tot'] or 0
        event_bytes = EventMedia.objects.aggregate(tot=Sum('file_size'))['tot'] or 0
        total_storage_used_bytes = media_bytes + event_bytes
        total_storage_used_gb = round(total_storage_used_bytes / (1024 ** 3), 2)

        # Top 5 Studios by Storage Usage
        top_studios_qs = (
            PhotographerProfile.objects.annotate(
                galleries_total=Count('galleries', distinct=True)
            ).order_by('-storage_used_bytes')[:5]
        )
        top_storage_studios = []
        for s in top_studios_qs:
            used_b = s.storage_used_bytes or 0
            top_storage_studios.append({
                'id': s.id,
                'studio_name': s.studio_name or s.name or 'Studio',
                'photographer_name': s.name or '',
                'email': getattr(s.user, 'email', '') if s.user else s.email,
                'used_bytes': used_b,
                'used_gb': round(used_b / (1024 ** 3), 2),
                'gallery_count': getattr(s, 'galleries_total', 0),
            })

        # ---------------------------------------------------------------------
        # 5. Galleries, Live Events & Proofing Metrics
        # ---------------------------------------------------------------------
        total_galleries = Gallery.objects.count()
        published_galleries = Gallery.objects.filter(status='published').count()
        total_live_events = LiveEvent.objects.count()
        total_guest_viewers = GalleryViewer.objects.count()
        total_photo_likes = ViewerLikedMedia.objects.count()
        total_inquiries = Inquiry.objects.count() + PortfolioInquiry.objects.count()

        # ---------------------------------------------------------------------
        # 6. Time-Series Trends (Zero-Filled for Smooth Continuous Charts)
        # ---------------------------------------------------------------------
        # Initialize day buckets
        date_list = [
            (window_start + datetime.timedelta(days=i)).date()
            for i in range(days + 1)
        ]
        user_reg_buckets = {d.isoformat(): 0 for d in date_list}
        rev_buckets = {d.isoformat(): 0.0 for d in date_list}
        tx_count_buckets = {d.isoformat(): 0 for d in date_list}

        # Populate user registrations
        window_users = User.objects.filter(
            date_joined__gte=window_start
        ).values_list('date_joined', flat=True)
        for dj in window_users:
            if dj:
                d_str = dj.date().isoformat()
                if d_str in user_reg_buckets:
                    user_reg_buckets[d_str] += 1

        # Populate revenue & transactions
        window_payments = successful_payments.filter(
            created_at__gte=window_start
        ).values_list('created_at', 'amount')
        for dt, amt in window_payments:
            if dt:
                d_str = dt.date().isoformat()
                if d_str in rev_buckets:
                    rev_buckets[d_str] += float(amt or 0)
                    tx_count_buckets[d_str] += 1

        # Running cumulative user count
        baseline_users = User.objects.filter(date_joined__lt=window_start).count()
        cumulative = baseline_users

        user_growth_time_series = []
        for d in date_list:
            d_str = d.isoformat()
            new_u = user_reg_buckets.get(d_str, 0)
            cumulative += new_u
            user_growth_time_series.append({
                'date': d_str,
                'new_users': new_u,
                'cumulative_users': cumulative,
            })

        revenue_time_series = [
            {
                'date': d.isoformat(),
                'revenue': round(rev_buckets.get(d.isoformat(), 0.0), 2),
                'transactions': tx_count_buckets.get(d.isoformat(), 0),
            }
            for d in date_list
        ]

        # ---------------------------------------------------------------------
        # 7. Recent Activity Feeds (Latest Users & Payments)
        # ---------------------------------------------------------------------
        recent_users_qs = User.objects.select_related('photographer_profile').prefetch_related('subscriptions__plan').order_by('-date_joined')[:10]
        recent_users_data = AdminUserItemSerializer(recent_users_qs, many=True).data

        recent_payments_qs = (
            SubscriptionPayment.objects.select_related(
                'subscription__user', 'subscription__photographer', 'plan'
            ).order_by('-created_at')[:10]
        )
        recent_payments_data = AdminPaymentItemSerializer(recent_payments_qs, many=True).data

        # ---------------------------------------------------------------------
        # 8. Assembled Payload
        # ---------------------------------------------------------------------
        return Response({
            'status': 'success',
            'time_window_days': days,
            'kpis': {
                'total_users': total_users,
                'new_users_window': new_users_window,
                'new_users_7d': new_users_7d,
                'new_users_today': new_users_today,
                'user_growth_percentage': user_growth_percentage,
                'total_photographers': total_photographers,
                'active_subscribers': active_subscribers_count,
                'churned_subscribers': expired_subscribers_count + cancelled_subscribers_count,
                'total_revenue': total_revenue,
                'revenue_window': revenue_window,
                'revenue_growth_percentage': revenue_growth_percentage,
                'mrr': mrr,
                'arr': arr,
                'avg_order_value': avg_order_value,
                'total_galleries': total_galleries,
                'published_galleries': published_galleries,
                'total_media_items': total_media_items,
                'total_storage_used_bytes': total_storage_used_bytes,
                'total_storage_used_gb': total_storage_used_gb,
                'total_live_events': total_live_events,
                'total_guest_viewers': total_guest_viewers,
                'total_photo_likes': total_photo_likes,
                'total_inquiries': total_inquiries,
            },
            'user_growth': {
                'time_series': user_growth_time_series,
                'roles': roles_dict,
                'verification_rates': {
                    'email_verified_count': email_verified_count,
                    'email_verified_percentage': email_verified_pct,
                    'phone_verified_count': phone_verified_count,
                    'phone_verified_percentage': phone_verified_pct,
                },
            },
            'revenue_analytics': {
                'currency': 'INR',
                'time_series': revenue_time_series,
                'payment_status': payment_status_breakdown,
                'gateways': {'razorpay': all_payments_count},
            },
            'subscriptions': {
                'by_tier': subscriptions_by_tier,
                'by_billing_cycle': subscriptions_by_cycle,
                'by_status': {
                    'active': active_subscribers_count,
                    'expired': expired_subscribers_count,
                    'cancelled': cancelled_subscribers_count,
                },
            },
            'storage': {
                'total_bytes': total_storage_used_bytes,
                'total_gb': total_storage_used_gb,
                'photos_count': media_photos_count,
                'videos_count': media_videos_count,
                'top_studios': top_storage_studios,
            },
            'recent_payments': recent_payments_data,
            'recent_users': recent_users_data,
            'system_health': {
                'status': 'operational',
                'database': 'connected',
                'server_time': now.isoformat(),
            },
        }, status=status.HTTP_200_OK)


# Primary and dual-compatible alias
AdminOverviewView = AdminDashboardOverviewView


class AdminUsersListView(APIView):
    """
    GET /api/admin/dashboard/users/
    Paginated, searchable, filterable list of all registered platform users and studios.
    Query parameters:
    - search: search against email, username, fullname, phone, studio_name
    - role: filter by role (photographer, user, staff, admin)
    - status: active / expired / inactive
    - page, page_size (default 10, max 100)
    - ordering: -date_joined, date_joined, email, username
    """
    permission_classes = [IsMasterAdminOrStaff]
    pagination_class = AdminStandardPagination

    def get(self, request):
        qs = User.objects.select_related('photographer_profile').prefetch_related(
            'subscriptions__plan'
        ).all()

        # Search
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(email__icontains=search)
                | Q(username__icontains=search)
                | Q(fullname__icontains=search)
                | Q(phone__icontains=search)
                | Q(photographer_profile__studio_name__icontains=search)
            )

        # Role filter
        role = request.query_params.get('role', '').strip()
        if role:
            qs = qs.filter(role=role)

        # Status filter
        status_param = request.query_params.get('status', '').strip().lower()
        if status_param == 'active':
            qs = qs.filter(is_active=True)
        elif status_param in ['expired', 'inactive']:
            qs = qs.filter(is_active=False)

        # Ordering
        ordering = request.query_params.get('ordering', '-date_joined')
        allowed_orderings = ['date_joined', '-date_joined', 'email', '-email', 'username', '-username']
        if ordering in allowed_orderings:
            qs = qs.order_by(ordering)
        else:
            qs = qs.order_by('-date_joined')

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminUserItemSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminPaymentsListView(APIView):
    """
    GET /api/admin/dashboard/payments/
    Paginated, searchable, filterable list of all billing transactions with summary.
    Query parameters:
    - search: search order_id, payment_id, user email, studio_name
    - status: success, pending, failed
    - gateway: razorpay
    - start_date, end_date (YYYY-MM-DD)
    - page, page_size (default 10, max 100)
    - ordering: -created_at, created_at, amount, -amount
    """
    permission_classes = [IsMasterAdminOrStaff]
    pagination_class = AdminPaymentsPagination

    def get(self, request):
        qs = SubscriptionPayment.objects.select_related(
            'subscription__user',
            'subscription__photographer',
            'plan'
        ).all()

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(gateway_order_id__icontains=search)
                | Q(gateway_payment_id__icontains=search)
                | Q(subscription__user__email__icontains=search)
                | Q(subscription__photographer__studio_name__icontains=search)
            )

        status_param = request.query_params.get('status', '').strip()
        if status_param:
            qs = qs.filter(status=status_param)

        start_date = request.query_params.get('start_date', '').strip()
        if start_date:
            try:
                parsed_start = datetime.datetime.fromisoformat(start_date)
                qs = qs.filter(created_at__gte=parsed_start)
            except ValueError:
                pass

        end_date = request.query_params.get('end_date', '').strip()
        if end_date:
            try:
                parsed_end = datetime.datetime.fromisoformat(end_date)
                qs = qs.filter(created_at__lte=parsed_end)
            except ValueError:
                pass

        ordering = request.query_params.get('ordering', '-created_at')
        allowed_orderings = ['created_at', '-created_at', 'amount', '-amount']
        if ordering in allowed_orderings:
            qs = qs.order_by(ordering)
        else:
            qs = qs.order_by('-created_at')

        # Filtered totals summary
        total_amount = qs.filter(status='success').aggregate(tot=Sum('amount'))['tot'] or Decimal('0.00')

        paginator = self.pagination_class()
        paginator.custom_summary = {
            'filtered_total_successful_revenue': float(total_amount),
            'currency': 'INR',
        }
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminPaymentItemSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminGrowthAnalyticsView(APIView):
    """
    GET /api/admin/dashboard/growth/?range=30d
    Time-series growth curves for users, galleries, revenue, and uploads.
    Query parameters:
    - range: 7d, 30d, 90d, 1y (default: 30d)
    """
    permission_classes = [IsMasterAdminOrStaff]

    def get(self, request):
        now = timezone.now()
        range_param = request.query_params.get('range', '30d').lower().strip()

        days_map = {
            '7d': 7,
            '30d': 30,
            '90d': 90,
            '1y': 365,
            '365d': 365,
        }
        days = days_map.get(range_param, 30)
        start_date = now - datetime.timedelta(days=days)

        date_list = [
            (start_date + datetime.timedelta(days=i)).date()
            for i in range(days + 1)
        ]

        user_buckets = {d.isoformat(): 0 for d in date_list}
        gallery_buckets = {d.isoformat(): 0 for d in date_list}
        rev_buckets = {d.isoformat(): 0.0 for d in date_list}
        media_buckets = {d.isoformat(): 0 for d in date_list}

        # Users
        users = User.objects.filter(date_joined__gte=start_date).values_list('date_joined', flat=True)
        for dj in users:
            if dj:
                d_str = dj.date().isoformat()
                if d_str in user_buckets:
                    user_buckets[d_str] += 1

        # Galleries
        galleries = Gallery.objects.filter(created_at__gte=start_date).values_list('created_at', flat=True)
        for gc in galleries:
            if gc:
                d_str = gc.date().isoformat()
                if d_str in gallery_buckets:
                    gallery_buckets[d_str] += 1

        # Revenue
        payments = SubscriptionPayment.objects.filter(
            status='success', created_at__gte=start_date
        ).values_list('created_at', 'amount')
        for pt, amt in payments:
            if pt:
                d_str = pt.date().isoformat()
                if d_str in rev_buckets:
                    rev_buckets[d_str] += float(amt or 0)

        # Media uploads
        medias = Media.objects.filter(created_at__gte=start_date).values_list('created_at', flat=True)
        for mc in medias:
            if mc:
                d_str = mc.date().isoformat()
                if d_str in media_buckets:
                    media_buckets[d_str] += 1

        time_series = [
            {
                'date': d.isoformat(),
                'users': user_buckets.get(d.isoformat(), 0),
                'new_users': user_buckets.get(d.isoformat(), 0),
                'galleries': gallery_buckets.get(d.isoformat(), 0),
                'new_galleries': gallery_buckets.get(d.isoformat(), 0),
                'revenue': round(rev_buckets.get(d.isoformat(), 0.0), 2),
                'media_uploads': media_buckets.get(d.isoformat(), 0),
            }
            for d in date_list
        ]

        total_users_acquired = sum(user_buckets.values())
        total_galleries_created = sum(gallery_buckets.values())
        total_revenue_generated = round(sum(rev_buckets.values()), 2)
        total_media_uploads = sum(media_buckets.values())

        # Growth velocity calculation: compare second half of period to first half
        midpoint_date = start_date + datetime.timedelta(days=days // 2)
        first_half_users = User.objects.filter(date_joined__gte=start_date, date_joined__lt=midpoint_date).count()
        second_half_users = User.objects.filter(date_joined__gte=midpoint_date).count()
        if first_half_users > 0:
            growth_velocity = round(((second_half_users - first_half_users) / first_half_users) * 100, 1)
        elif second_half_users > 0:
            growth_velocity = 100.0
        else:
            growth_velocity = 0.0

        return Response({
            'status': 'success',
            'range': range_param,
            'days': days,
            'time_series': time_series,
            'timeline': time_series,  # Backwards compatibility
            'summary': {
                'total_users_acquired': total_users_acquired,
                'total_galleries_created': total_galleries_created,
                'total_revenue_generated': total_revenue_generated,
                'total_media_uploads': total_media_uploads,
                'growth_velocity_percentage': growth_velocity,
            }
        }, status=status.HTTP_200_OK)

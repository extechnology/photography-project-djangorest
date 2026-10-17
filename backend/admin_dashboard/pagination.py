from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class AdminStandardPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class AdminPaymentsPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        summary = getattr(self, 'custom_summary', {
            'filtered_total_successful_revenue': 0.0,
            'currency': 'INR'
        })
        return Response({
            'count': self.page.paginator.count,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'summary': summary,
            'results': data
        })


# Compatibility alias
StandardResultsSetPagination = AdminStandardPagination

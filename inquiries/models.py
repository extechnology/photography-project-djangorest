"""
Database models for client gallery & portfolio inquiries.
Maps to unified PortfolioInquiry schema.
"""
from django.db import models
from django.conf import settings
from galleries.models import Gallery
from portfolio.models import PortfolioInquiry as Inquiry

__all__ = ['Inquiry', 'Gallery']

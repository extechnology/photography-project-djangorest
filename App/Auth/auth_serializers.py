
import re
import random

from rest_framework import serializers
from django.conf import settings
from rest_framework.response import Response
from rest_framework import status

from .auth_models import *
from .auth_emails import *

from django.db.models import Q




class PasswordlessSendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        return value.strip().lower()


class PasswordlessVerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    otp = serializers.CharField(max_length=6, required=True)
    fullname = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(
        choices=User.Role.choices,
        default=User.Role.PHOTOGRAPHER,
        required=False
    )

    def validate_email(self, value):
        return value.strip().lower()

    def validate_otp(self, value):
        return value.strip()
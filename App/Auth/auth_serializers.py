from rest_framework import serializers
from django.core.mail import send_mail
from django.utils import timezone
from django.conf import settings
from rest_framework.response import Response
from rest_framework import status

from .auth_models import *
from .auth_emails import *

import platform
import datetime
import urllib.parse
import re
import random
from django.db.models import Q


class UserRegistrationSerializer(serializers.ModelSerializer):
    identifier = serializers.CharField(required=False)
    username = serializers.CharField(required=True)

    class Meta:
        model = User
        fields = "__all__"

    def create(self, validated_data):
        otp = str(random.randint(100000, 999999))
        identifier = validated_data.get("identifier")
        username = validated_data.get("username")
        
        if not identifier:
            raise serializers.ValidationError({"message": "Either email or phone number must be provided"})

        if User.objects.filter(username=username).exists():
            raise serializers.ValidationError({"message": "This username is already taken"})

        if re.match(r"[^@]+@[^@]+\.[^@]+", identifier):
            if User.objects.filter(email=identifier).exists():
                raise serializers.ValidationError({"message": "This email is already registered"})
            RegistrationOTP.objects.create(identifier=identifier, otp=otp)
            send_registration_otp_email(identifier, otp)

        elif identifier.isdigit():
            if User.objects.filter(phone=identifier).exists():
                raise serializers.ValidationError({"message": "This phone number is already registered"})
            RegistrationOTP.objects.create(identifier=identifier, otp=otp)

        else:
            raise serializers.ValidationError({"message": "Invalid identifier. Must be an email or phone number"})
        
        return Response({'message': 'OTP sent to your email/phone for verification'}, status=status.HTTP_201_CREATED)


class ResentOTPSerializer(serializers.Serializer):
    
    identifier = serializers.CharField(required=False)
    username = serializers.CharField(required=False)

    def create(self, validated_data):
        
        identifier = validated_data.get("identifier")
        
        if not identifier:
            raise serializers.ValidationError("Either email or phone must be provided")
        
        if re.match(r"[^@]+@[^@]+\.[^@]+", identifier):
            
            otp = str(random.randint(100000, 999999))
            
            RegistrationOTP.objects.create(identifier=identifier, otp=otp)
            
            send_registration_otp_email(identifier, otp)

        elif identifier.isdigit() and len(identifier):
            
            otp = str(random.randint(100000, 999999))
            
            RegistrationOTP.objects.create(identifier=identifier, otp=otp)

        return {'message': 'OTP - Sended','otp': otp}
        
class EmailOTPVerifySerializer(serializers.Serializer):
    identifier = serializers.CharField(required=True)
    otp = serializers.CharField(max_length=6)
    password = serializers.CharField(write_only=True, required=True)

    def validate(self, data):
        identifier = data.get("identifier")

        try:
            otp_instance = RegistrationOTP.objects.get(identifier=identifier)
        except RegistrationOTP.DoesNotExist:
            raise serializers.ValidationError({"message": "Invalid OTP or identifier"})

        if otp_instance.otp != data.get("otp"):
            raise serializers.ValidationError({"message": "Invalid OTP"})

        if not otp_instance.is_valid(data.get("otp")):
            raise serializers.ValidationError({"message": "OTP expired or already used"})

        return data

    def create(self, validated_data):
        identifier = validated_data.get("identifier")
        password = validated_data.get("password")

        if identifier.isdigit():
            user = User.objects.filter(phone=identifier).first()
        else:
            user = User.objects.filter(email=identifier).first()

        if user:
            user.set_password(password)

            if identifier.isdigit():
                user.is_phone_verified = True
            else:
                user.is_email_verified = True

            user.save()

        else:
            if identifier.isdigit():
                user = User.objects.create_user(
                    username=identifier,
                    phone=identifier,
                    password=password,
                )
                user.is_phone_verified = True
            else:
                user = User.objects.create_user(
                    username=identifier,
                    email=identifier,
                    password=password,
                )
                user.is_email_verified = True

            user.save()

        RegistrationOTP.objects.filter(identifier=identifier).delete()

        return user

class ResetPasswordSerializer(serializers.Serializer):
    
    identifier = serializers.CharField(required=False)
    
    class Meta:
        model = ResetPasswordOTP
        fields = "__all__"
    
    def create(self, validated_data):
        identifier = validated_data.get("identifier")
        
        print(identifier)
        if not identifier:
            raise serializers.ValidationError("Either email or phone must be provided")
        
        if not User.objects.filter(Q(email=identifier) | Q(phone=identifier) | Q(username=identifier)).exists():
            raise serializers.ValidationError("Invalid identifier")
        
        if re.match(r"[^@]+@[^@]+\.[^@]+", identifier):
            otp = str(random.randint(100000, 999999))
            ResetPasswordOTP.objects.create(identifier=identifier, otp=otp)
            forgot_password_otp_email(identifier, otp)

        elif identifier.isdigit() and len(identifier):
            otp = str(random.randint(100000, 999999))
            ResetPasswordOTP.objects.create(identifier=identifier, otp=otp)

        return {'message': 'One time password sent to your email/phone for verification'}

class ResendResetPasswordOTPSerializer(serializers.Serializer):
    identifier = serializers.CharField(required=False)

    def create(self, validated_data):
        identifier = validated_data.get("identifier")
        
        if not identifier:
            raise serializers.ValidationError("Either email or phone must be provided")
        
        
        
        if re.match(r"[^@]+@[^@]+\.[^@]+", identifier):
            otp = str(random.randint(100000, 999999))
            ResetPasswordOTP.objects.create(identifier=identifier, otp=otp)
            forgot_password_otp_email(identifier, otp)

        elif identifier.isdigit() and len(identifier):
            otp = str(random.randint(100000, 999999))
            ResetPasswordOTP.objects.create(identifier=identifier, otp=otp)

        return {'message': 'One time password sent to your email/phone for verification'}

class VerifyResetPasswordSerializer(serializers.Serializer):
    
    identifier = serializers.CharField(required=False)
    otp = serializers.CharField(max_length=6)
    new_password = serializers.CharField(write_only=True, required=False)
    
    def validate(self, data):
        
        identifier = data.get("identifier")
        
        if not identifier:
            
            raise serializers.ValidationError("Either email or phone must be provided")
        
        try:
            
            otp_instance = ResetPasswordOTP.objects.get(identifier=identifier)
            
        except ResetPasswordOTP.DoesNotExist:
            
            raise serializers.ValidationError("Invalid OTP or identifier")
        
        if otp_instance.otp != data.get("otp"):
            
            raise serializers.ValidationError("Invalid OTP")
        
        if not otp_instance.is_valid(data.get("otp")):
            
            raise serializers.ValidationError("OTP has already been used or is invalid")

        return data
    
    def create(self, validated_data):
        
        identifier = validated_data.get("identifier")
        
        otp_instance = ResetPasswordOTP.objects.get(identifier=identifier)
        
        otp_instance.is_verified = True
        otp_instance.save()
        
        return {'message': 'OTP verified successfully'}

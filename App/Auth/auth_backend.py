# accounts/backends.py
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db import models
User = get_user_model()


class UsernameEmailPhoneBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Allow login with username OR email OR phone.
        """
        user = None
        if username:
            try:
                user = User.objects.get(
                    models.Q(username=username) |
                    models.Q(email=username) |
                    models.Q(phone=username)
                )
            except User.DoesNotExist:
                return None

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
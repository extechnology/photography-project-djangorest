from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.contrib.auth import get_user_model
from rest_framework.exceptions import AuthenticationFailed

User = get_user_model()


class CookieJWTAuthentication(JWTAuthentication):
    """
    Extends SimpleJWT's JWTAuthentication to inspect HTTP-only cookies ('access_token')
    when the Authorization: Bearer <token> header is not provided.
    """
    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            raw_token = self.get_raw_token(header)
            if raw_token is not None:
                validated_token = self.get_validated_token(raw_token)
                return self.get_user(validated_token), validated_token

        # Fallback to checking HTTP-only cookie
        raw_token = request.COOKIES.get('access_token')
        if raw_token:
            try:
                validated_token = self.get_validated_token(raw_token)
                return self.get_user(validated_token), validated_token
            except Exception:
                return None

        return None


def get_user_from_request(request):

    access_token = None

    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        access_token = auth_header.split(' ')[1]

    if not access_token:
        access_token = request.COOKIES.get('access_token')

    if not access_token:
        raise AuthenticationFailed("No access token provided.")

    try:
        token = AccessToken(access_token)
        user_id = token['user_id']
        user = User.objects.get(id=user_id)
        return user
    except Exception as e:
        raise AuthenticationFailed(f"Invalid or expired token: {str(e)}")
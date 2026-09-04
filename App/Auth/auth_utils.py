from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model
from rest_framework.exceptions import AuthenticationFailed

User = get_user_model()

def get_user_from_request(request):

    access_token = None

    # 1️⃣ Check Authorization header (Bearer <token>)
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        access_token = auth_header.split(' ')[1]

    # 2️⃣ Fallback: check cookie
    if not access_token:
        access_token = request.COOKIES.get('access_token')

    # 3️⃣ If still not found
    if not access_token:
        raise AuthenticationFailed("No access token provided.")

    # 4️⃣ Validate token
    try:
        token = AccessToken(access_token)
        user_id = token['user_id']
        user = User.objects.get(id=user_id)
        return user
    except Exception as e:
        raise AuthenticationFailed(f"Invalid or expired token: {str(e)}")
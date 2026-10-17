from rest_framework.permissions import BasePermission
from App.Auth.auth_models import User


class IsMasterAdminOrStaff(BasePermission):
    """
    Grants access only to authenticated system administrators or staff members.
    Supports is_superuser, is_staff, is_admin, or role in ['admin', 'staff'].
    """
    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False

        is_staff = getattr(user, 'is_staff', False)
        is_superuser = getattr(user, 'is_superuser', False)
        is_admin = getattr(user, 'is_admin', False)
        role = str(getattr(user, 'role', '')).lower().strip()

        return bool(
            is_staff
            or is_superuser
            or is_admin
            or role in ['admin', 'staff']
        )


# Dual-compatible alias
IsSuperAdminOrStaff = IsMasterAdminOrStaff

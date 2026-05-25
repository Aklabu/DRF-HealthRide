"""
Permission class for driver_app views.
Requires the request to have been authenticated via DriverJWTAuthentication
and have a valid request.driver attribute.
"""
from rest_framework.permissions import BasePermission


class IsDriver(BasePermission):
    """
    Grants access only to requests authenticated as a Driver.
    Works in conjunction with DriverJWTAuthentication.
    """
    message = 'Driver authentication required.'

    def has_permission(self, request, view):
        return bool(
            request.driver is not None
            and hasattr(request, 'driver')
        )

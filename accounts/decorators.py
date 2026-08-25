"""
Role-based authorization decorators and mixins for ClientSpace.

Usage in function-based views
──────────────────────────────
    from accounts.decorators import manager_required, staff_or_above

    @manager_required
    def delete_project(request, pk):
        ...

    @staff_or_above
    def project_detail(request, pk):
        ...

Usage in class-based views
──────────────────────────────
    from accounts.decorators import ManagerRequiredMixin

    class DeleteProjectView(ManagerRequiredMixin, DeleteView):
        ...

Authorization hierarchy
───────────────────────
    MANAGER   → full access
    STAFF     → read/write on assigned work; cannot manage users or delete projects
    CLIENT    → read-only on their own data; cannot see other clients' data

Unauthenticated requests are handled by LoginRequiredMiddleware before these
decorators ever run.  If somehow an unauthenticated request reaches a view
decorated with these, Django's @login_required wrapping still catches it.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils.decorators import method_decorator


# ──────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────

def _forbidden(request, reason="You do not have permission to perform this action."):
    """Return a styled 403 response."""
    return render(request, "403.html", {"reason": reason}, status=403)


def _role_required(*allowed_roles):
    """
    Factory that returns a decorator enforcing one of the allowed roles.
    Always wraps with @login_required first so unauthenticated users go
    to the login page rather than seeing a 403.
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if request.user.role in allowed_roles:
                return view_func(request, *args, **kwargs)
            return _forbidden(request)
        return wrapper
    return decorator


# ──────────────────────────────────────────────────────────────
# Public decorators
# ──────────────────────────────────────────────────────────────

def manager_required(view_func):
    """Only MANAGER role can access this view."""
    return _role_required("MANAGER")(view_func)


def staff_or_above(view_func):
    """MANAGER or STAFF can access this view."""
    return _role_required("MANAGER", "STAFF")(view_func)


def client_or_above(view_func):
    """Any authenticated user (MANAGER, STAFF, CLIENT) can access."""
    # All authenticated users pass; unauthenticated are caught by middleware.
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        return view_func(request, *args, **kwargs)
    return wrapper


# ──────────────────────────────────────────────────────────────
# Class-based view mixins
# ──────────────────────────────────────────────────────────────

class RoleRequiredMixin:
    """
    Base mixin. Set `allowed_roles` on the subclass.

    Example:
        class MyView(RoleRequiredMixin, View):
            allowed_roles = ["MANAGER", "STAFF"]
    """
    allowed_roles = []

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        if request.user.role not in self.allowed_roles:
            return _forbidden(request)
        return super().dispatch(request, *args, **kwargs)


class ManagerRequiredMixin(RoleRequiredMixin):
    """Only MANAGER role."""
    allowed_roles = ["MANAGER"]


class StaffOrAboveMixin(RoleRequiredMixin):
    """MANAGER or STAFF."""
    allowed_roles = ["MANAGER", "STAFF"]


# ──────────────────────────────────────────────────────────────
# Object-level ownership check helper
# ──────────────────────────────────────────────────────────────

def check_object_permission(request, obj, owner_field="user"):
    """
    Verifies that the logged-in CLIENT user actually owns `obj`.

    - MANAGER and STAFF bypass this check (they can access all objects).
    - CLIENT must be the owner; otherwise returns a 403 response.

    Returns None if access is allowed, or an HttpResponse (403) if denied.

    Usage in a view:
        def project_detail(request, pk):
            project = get_object_or_404(Project, pk=pk)
            denied = check_object_permission(request, project, owner_field="client__user")
            if denied:
                return denied
            ...
    """
    user = request.user

    if user.role in ("MANAGER", "STAFF"):
        return None  # permitted

    # For CLIENT: walk the dotted field path to the owner.
    owner = obj
    for part in owner_field.split("__"):
        owner = getattr(owner, part, None)
        if owner is None:
            break

    if owner != user:
        return _forbidden(
            request,
            "You are not authorised to access this resource.",
        )
    return None

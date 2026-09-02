from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from accounts.decorators import staff_or_above


@staff_or_above
def dashboard(request):
    """
    Main dashboard — accessible to MANAGER and STAFF only.
    CLIENT users are blocked at the middleware level (Stage 3) and also here
    by the @staff_or_above decorator as a second line of defence.
    """
    return render(request, 'dashboard/dashboard.html')

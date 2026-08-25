from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from accounts.decorators import manager_required


@login_required
def settings_page(request):
    """
    Application settings page.
    Currently accessible to any authenticated user (profile settings).
    Management-level settings should use @manager_required when added.
    """
    return render(request, "sett/settings.html")

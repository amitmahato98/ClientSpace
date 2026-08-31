from django.shortcuts import render

from accounts.decorators import staff_or_above


@staff_or_above
def settings_page(request):
    """
    Application settings page.
    Restricted to MANAGER and STAFF — CLIENT users are blocked by middleware
    Stage 3 and by this decorator as a second line of defence.
    Management-level settings should use @manager_required when added.
    """
    return render(request, "sett/settings.html")

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash, get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

from accounts.decorators import manager_required, staff_or_above

User = get_user_model()


@staff_or_above
def settings_page(request):
    """
    Application settings page.
    Restricted to MANAGER and STAFF — CLIENT users are blocked by middleware
    Stage 3 and by this decorator as a second line of defence.
    Management-level settings should use @manager_required when added.
    """
    user = request.user
    active_tab = "profile"

    if request.method == "POST":
        action = request.POST.get("action", "profile")

        if action == "profile":
            full_name = request.POST.get("full_name", "").strip()
            display_name = request.POST.get("display_name", "").strip()
            email = request.POST.get("email", "").strip()
            new_password = request.POST.get("new_password", "")
            confirm_password = request.POST.get("confirm_password", "")

            # Email uniqueness check
            if email and email != user.email:
                if User.objects.filter(email=email).exclude(pk=user.pk).exists():
                    messages.error(request, "This email address is already in use by another account.")
                    return render(request, "sett/settings.html", {"active_tab": "profile"})
                user.email = email

            # Full name update
            if full_name:
                name_parts = full_name.split(maxsplit=1)
                user.first_name = name_parts[0]
                user.last_name = name_parts[1] if len(name_parts) > 1 else ""
            else:
                user.first_name = ""
                user.last_name = ""

            # Display name update
            user.display_name = display_name

            # Profile picture upload
            if "profile_picture" in request.FILES:
                user.profile_picture = request.FILES["profile_picture"]

            # Password update logic
            if new_password or confirm_password:
                if new_password != confirm_password:
                    messages.error(request, "New password and confirm password do not match.")
                    return render(request, "sett/settings.html", {"active_tab": "profile"})
                elif len(new_password) < 6:
                    messages.error(request, "Password must be at least 6 characters long.")
                    return render(request, "sett/settings.html", {"active_tab": "profile"})
                else:
                    user.set_password(new_password)
                    user.save()
                    update_session_auth_hash(request, user)
                    messages.success(request, "Profile and password updated successfully!")
                    return redirect("sett:settings")

            user.save()
            messages.success(request, "Profile updated successfully!")
            return redirect("sett:settings")

    return render(request, "sett/settings.html", {"active_tab": active_tab})


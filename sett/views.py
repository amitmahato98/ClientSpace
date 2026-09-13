from django.contrib import messages
from django.contrib.auth import update_session_auth_hash, get_user_model
from django.shortcuts import render, redirect

from accounts.decorators import staff_or_above
from accounts.models import OrganizationMembership

User = get_user_model()


@staff_or_above
def settings_page(request):

    user = request.user
    active_tab = "profile"

    # ==================================================
    # GET ORGANIZATION FOR STAFF AND MANAGER
    # ==================================================

    organization = None

    membership = OrganizationMembership.objects.filter(
        user=user
    ).select_related("organization").first()

    if membership:
        organization = membership.organization

    # ==================================================
    # POST REQUEST
    # ==================================================

    if request.method == "POST":

        action = request.POST.get("action", "profile")

        # ==================================================
        # PROFILE
        # ==================================================

        if action == "profile":

            full_name = request.POST.get(
                "full_name",
                ""
            ).strip()

            display_name = request.POST.get(
                "display_name",
                ""
            ).strip()

            email = request.POST.get(
                "email",
                ""
            ).strip()

            new_password = request.POST.get(
                "new_password",
                ""
            )

            confirm_password = request.POST.get(
                "confirm_password",
                ""
            )

            # ----------------------------------------------
            # Email uniqueness check
            # ----------------------------------------------

            if email and email != user.email:

                if User.objects.filter(
                    email=email
                ).exclude(
                    pk=user.pk
                ).exists():

                    messages.error(
                        request,
                        "This email address is already in use by another account."
                    )

                    return render(
                        request,
                        "sett/settings.html",
                        {
                            "active_tab": "profile",
                            "organization": organization,
                        }
                    )

                user.email = email

            # ----------------------------------------------
            # Full name
            # ----------------------------------------------

            if full_name:

                name_parts = full_name.split(
                    maxsplit=1
                )

                user.first_name = name_parts[0]

                user.last_name = (
                    name_parts[1]
                    if len(name_parts) > 1
                    else ""
                )

            else:

                user.first_name = ""
                user.last_name = ""

            # ----------------------------------------------
            # Display name
            # ----------------------------------------------

            user.display_name = display_name

            # ----------------------------------------------
            # Profile picture
            # ----------------------------------------------

            if "profile_picture" in request.FILES:

                user.profile_picture = request.FILES[
                    "profile_picture"
                ]

                try:
                    from notifications.service import notify_account_activity
                    notify_account_activity(
                        recipient=user,
                        message="Security notice: You updated your profile picture.",
                        link="/settings/?tab=profile",
                    )
                except Exception:
                    pass

            # ----------------------------------------------
            # Password
            # ----------------------------------------------

            if new_password or confirm_password:

                if new_password != confirm_password:

                    messages.error(
                        request,
                        "New password and confirm password do not match."
                    )

                    return render(
                        request,
                        "sett/settings.html",
                        {
                            "active_tab": "profile",
                            "organization": organization,
                        }
                    )

                elif len(new_password) < 6:

                    messages.error(
                        request,
                        "Password must be at least 6 characters long."
                    )

                    return render(
                        request,
                        "sett/settings.html",
                        {
                            "active_tab": "profile",
                            "organization": organization,
                        }
                    )

                else:

                    user.set_password(
                        new_password
                    )

                    user.save()

                    update_session_auth_hash(
                        request,
                        user
                    )

                    messages.success(
                        request,
                        "Profile and password updated successfully!"
                    )

                    return redirect(
                        "sett:settings"
                    )

            # ----------------------------------------------
            # Save profile
            # ----------------------------------------------

            user.save()

            messages.success(
                request,
                "Profile updated successfully!"
            )

            return redirect(
                "sett:settings"
            )

        # ==================================================
        # ORGANIZATION
        # ==================================================

        elif action == "organization":

            # ----------------------------------------------
            # SECURITY CHECK
            #
            # Only MANAGER can modify organization details.
            # Staff can view them, but cannot update them.
            # ----------------------------------------------

            if user.role != user.Role.MANAGER:

                messages.error(
                    request,
                    "You do not have permission to update organization details."
                )

                return redirect(
                    "sett:settings"
                )

            # ----------------------------------------------
            # Make sure organization exists
            # ----------------------------------------------

            if not organization:

                messages.error(
                    request,
                    "No organization was found for your account."
                )

                return redirect(
                    "sett:settings"
                )

            # ----------------------------------------------
            # Organization name
            # ----------------------------------------------

            organization.name = request.POST.get(
                "name",
                organization.name
            ).strip()

            # ----------------------------------------------
            # Description
            # ----------------------------------------------

            organization.description = request.POST.get(
                "description",
                organization.description
            ).strip()

            # ----------------------------------------------
            # Organization email
            # ----------------------------------------------

            organization.email = request.POST.get(
                "organization_email",
                organization.email
            ).strip()

            # ----------------------------------------------
            # Phone
            # ----------------------------------------------

            organization.phone = request.POST.get(
                "phone",
                organization.phone
            ).strip()

            # ----------------------------------------------
            # Address
            # ----------------------------------------------

            organization.address = request.POST.get(
                "address",
                organization.address
            ).strip()

            # ----------------------------------------------
            # Website
            # ----------------------------------------------

            organization.website = request.POST.get(
                "website",
                organization.website
            ).strip()

            # ----------------------------------------------
            # Organization logo
            # ----------------------------------------------

            if "logo" in request.FILES:

                organization.logo = request.FILES[
                    "logo"
                ]

            # ----------------------------------------------
            # Save organization
            # ----------------------------------------------

            organization.save()

            messages.success(
                request,
                "Organization details updated successfully!"
            )

            return redirect(
                "sett:settings"
            )

        # ==================================================
        # NOTIFICATIONS
        # ==================================================

        elif action == "notifications":

            from notifications.models import NotificationSetting

            settings_obj, _ = NotificationSetting.objects.get_or_create(user=user)
            settings_obj.payment_received = request.POST.get("payment_received") == "on"
            settings_obj.deadline_reminder = request.POST.get("deadline_reminder") == "on"
            settings_obj.overdue_alert = request.POST.get("overdue_alert") == "on"
            settings_obj.client_portal_viewed = request.POST.get("client_portal_viewed") == "on"
            settings_obj.team_member_joined = request.POST.get("team_member_joined") == "on"
            settings_obj.weekly_summary = request.POST.get("weekly_summary") == "on"
            settings_obj.account_activity = request.POST.get("account_activity") == "on"
            settings_obj.save()

            messages.success(
                request,
                "Notification preferences updated successfully!"
            )

            return redirect(
                "/settings/?tab=notification"
            )

    # ==================================================
    # RENDER SETTINGS PAGE
    # ==================================================

    from notifications.models import NotificationSetting
    notification_settings, _ = NotificationSetting.objects.get_or_create(user=user)

    return render(
        request,
        "sett/settings.html",
        {
            "active_tab": active_tab,
            "organization": organization,
            "notification_settings": notification_settings,
        }
    )


from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import json


@staff_or_above
@require_http_methods(["POST"])
def toggle_notification_setting_ajax(request):
    """
    AJAX endpoint for instant toggle of a notification setting in Settings.
    Returns JSON with updated state and recalculates unread notification count.
    """
    from notifications.models import NotificationSetting
    from notifications.views import _get_active_notifications_qs

    try:
        data = json.loads(request.body.decode("utf-8"))
        setting_key = data.get("setting")
        enabled = bool(data.get("enabled"))
    except Exception:
        setting_key = request.POST.get("setting")
        enabled = request.POST.get("enabled") in ["true", "True", "1", "on"]

    valid_keys = [
        "payment_received",
        "deadline_reminder",
        "overdue_alert",
        "client_portal_viewed",
        "team_member_joined",
        "weekly_summary",
        "account_activity",
    ]

    if setting_key not in valid_keys:
        return JsonResponse({"success": False, "error": "Invalid notification setting."}, status=400)

    settings_obj, _ = NotificationSetting.objects.get_or_create(user=request.user)
    setattr(settings_obj, setting_key, enabled)
    settings_obj.save(update_fields=[setting_key, "updated_at"])

    unread_count = _get_active_notifications_qs(request.user).filter(is_read=False).count()

    return JsonResponse({
        "success": True,
        "setting": setting_key,
        "enabled": enabled,
        "unread_count": unread_count,
        "message": f"Notification preference saved.",
    })
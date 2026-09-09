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
    # GET ORGANIZATION FOR MANAGER
    # ==================================================

    organization = None

    if user.role == user.Role.MANAGER:

        membership = OrganizationMembership.objects.filter(
            user=user,
            role=OrganizationMembership.Role.MANAGER
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
            # Security check
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
    # RENDER SETTINGS PAGE
    # ==================================================

    return render(
        request,
        "sett/settings.html",
        {
            "active_tab": active_tab,
            "organization": organization,
        }
    )
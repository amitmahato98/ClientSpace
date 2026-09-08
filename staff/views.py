from django.contrib.auth import get_user_model
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.db.models import Prefetch
from django.core.mail import send_mail
from django.core.signing import (
    TimestampSigner,
    BadSignature,
    SignatureExpired,
)
from django.contrib import messages
from django.urls import reverse

from .forms import Add_staffForm, StaffSetupForm, StaffAssignmentForm
from .models import Staff,StaffAssignment
from projects.models import Project

from accounts.models import OrganizationMembership,Organization


User = get_user_model()

signer = TimestampSigner()


@login_required
def staff(request):

    # =====================================================
    # STAFF USER
    # =====================================================

    if request.user.role == request.user.Role.STAFF:

        staff_member = request.user.staff_profile

        # ---------------------------------------------
        # MY ACTIVE ASSIGNMENTS
        # ---------------------------------------------

        active_assignments = StaffAssignment.objects.filter(
            staff=staff_member,
            is_active=True
        ).select_related(
            "project",
            "assigned_by"
        ).order_by(
            "-assigned_at"
        )

        # ---------------------------------------------
        # MY COMPLETED / PREVIOUS ASSIGNMENTS
        # ---------------------------------------------

        completed_assignments = StaffAssignment.objects.filter(
            staff=staff_member,
            is_active=False
        ).select_related(
            "project",
            "assigned_by"
        ).order_by(
            "-completed_at"
        )

        # ---------------------------------------------
        # OTHER STAFF IN SAME ORGANIZATION
        # ---------------------------------------------

        fellow_staff = Staff.objects.filter(
            organization=staff_member.organization,
            user__isnull=False
        ).exclude(
            id=staff_member.id
        ).select_related(
            "user"
        ).order_by(
            "first_name",
            "last_name"
        )
        manager = OrganizationMembership.objects.filter(
        organization=staff_member.organization,
        role=OrganizationMembership.Role.MANAGER
    ).select_related("user").first()

        # ---------------------------------------------
        # COUNTS
        # ---------------------------------------------

        active_task_count = active_assignments.count()

        completed_task_count = completed_assignments.count()

        fellow_staff_count = fellow_staff.count()

        return render(
            request,
            "staff/staff_only_dashboard.html",
            {
                "staff": staff_member,
                "manager": manager,
                "assignments": active_assignments,
                "completed_assignments": completed_assignments,
                "fellow_staff": fellow_staff,

                "active_task_count": active_task_count,
                "completed_task_count": completed_task_count,
                "fellow_staff_count": fellow_staff_count,
            }
        )


    # =====================================================
    # MANAGER USER
    # =====================================================

    membership = OrganizationMembership.objects.filter(
        user=request.user,
        role=OrganizationMembership.Role.MANAGER
    ).first()

    if not membership:
        return redirect("dashboard")

    organization = membership.organization

    active_assignments = StaffAssignment.objects.filter(
        is_active=True
    ).select_related("project")

    staff_members = Staff.objects.filter(
        organization=organization,
        user__isnull=False
    ).select_related(
        "user"
    ).prefetch_related(
        Prefetch(
            "assignments",
            queryset=active_assignments,
            to_attr="active_assignments"
        )
    )

    total_staff = staff_members.count()

    available_staff = staff_members.filter(
        status="Available"
    ).count()

    working_staff = staff_members.filter(
        status="Working"
    ).count()

    active_tasks = StaffAssignment.objects.filter(
        staff__organization=organization,
        is_active=True
    ).count()

    return render(
        request,
        "staff/staff.html",
        {
            "staff_members": staff_members,
            "total_staff": total_staff,
            "available_staff": available_staff,
            "working_staff": working_staff,
            "active_tasks": active_tasks,
        }
    )




@login_required
def add_staff(request):

    membership = OrganizationMembership.objects.filter(
        user=request.user,
        role=OrganizationMembership.Role.MANAGER
    ).first()

    if not membership:
        return redirect("dashboard")

    organization = membership.organization

    if request.method == "POST":

        form = Add_staffForm(request.POST)

        if form.is_valid():

            staff_member = form.save(commit=False)

            staff_member.created_by = request.user
            staff_member.organization = organization
            staff_member.user = None
            staff_member.project = None
            staff_member.status = "Available"

            staff_member.save()

            token = signer.sign(
                str(staff_member.pk)
            )

            setup_url = request.build_absolute_uri(
                reverse(
                    "staff_setup",
                    kwargs={
                        "token": token
                    }
                )
            )

            send_mail(
                subject="Staff Account Setup Invitation",

                message=(
                    f"Hello {staff_member.first_name},\n\n"
                    f"You have been invited to join "
                    f"{organization.name} as a staff member.\n\n"
                    f"Please use the link below to set up "
                    f"your account:\n\n"
                    f"{setup_url}\n\n"
                    f"Through this link you will create your "
                    f"username, password, and job role.\n\n"
                    f"This invitation link will expire in 7 days.\n\n"
                    f"Thank you."
                ),

                from_email=None,

                recipient_list=[
                    staff_member.email
                ],
            )
            messages.success(
                 request,
                f"Invitation sent successfully to {staff_member.email}."
            )

            return redirect("staff")

    else:

        form = Add_staffForm()

    return render(
        request,
        "staff/add_staff.html",
        {
            "form": form
        }
    )




def staff_setup(request, token):

    # --------------------------------
    # Validate invitation token
    # --------------------------------

    try:

        staff_id = signer.unsign(
            token,
            max_age=60 * 60 * 24 * 7
        )

        staff_member = Staff.objects.get(
            pk=staff_id
        )

    except (
        BadSignature,
        SignatureExpired,
        Staff.DoesNotExist
    ):

        return render(
            request,
            "staff/setup_invalid.html"
        )

    # --------------------------------
    # Prevent invitation reuse
    # --------------------------------

    if staff_member.user is not None:

        return render(
            request,
            "staff/setup_invalid.html"
        )

    # --------------------------------
    # Handle account setup
    # --------------------------------

    if request.method == "POST":

        form = StaffSetupForm(
            request.POST
        )

        if form.is_valid():

            # --------------------------------
            # Create User account
            # --------------------------------

            user = User.objects.create_user(
                username=form.cleaned_data["username"],
                email=staff_member.email,
                first_name=staff_member.first_name,
                last_name=staff_member.last_name,
                password=form.cleaned_data["password"],
                role=User.Role.STAFF,
            )

            # --------------------------------
            # Connect User to Staff
            # --------------------------------

            staff_member.user = user

            # Save job role
            staff_member.role = form.cleaned_data["role"]

            staff_member.save()

            # --------------------------------
            # Create organization membership
            # --------------------------------

            OrganizationMembership.objects.create(
                user=user,
                organization=staff_member.organization,
                role=OrganizationMembership.Role.STAFF
            )

            # Send staff to login
            return redirect("accounts:login")

    else:

        form = StaffSetupForm()

    # --------------------------------
    # Display setup page
    # --------------------------------

    return render(
        request,
        "staff/staff_setup.html",
        {
            "form": form,
            "staff": staff_member,
        }
    )





@login_required
def assign_work(request):

    membership = OrganizationMembership.objects.filter(
        user=request.user,
        role=OrganizationMembership.Role.MANAGER
    ).first()

    if not membership:
        return redirect("dashboard")

    organization = membership.organization

    staff_id = request.GET.get("staff")

    if request.method == "POST":

        form = StaffAssignmentForm(request.POST)

        form.fields["staff"].queryset = Staff.objects.filter(
            organization=organization,
            user__isnull=False
        )

        form.fields["project"].queryset = Project.objects.filter(
            organization=organization
        )

        if form.is_valid():

            assignment = form.save(commit=False)

            assignment.assigned_by = request.user

            assignment.save()

            staff_member = assignment.staff
            staff_member.status = "Working"
            staff_member.save(update_fields=["status"])

            return redirect("staff")

    else:

        form = StaffAssignmentForm()

        form.fields["staff"].queryset = Staff.objects.filter(
            organization=organization,
            user__isnull=False
        )

        form.fields["project"].queryset = Project.objects.filter(
            organization=organization
        )

        if staff_id:
            form.initial["staff"] = staff_id

    return render(
        request,
        "staff/assign_work.html",
        {
            "form": form
        }
    )


@login_required
def staff_manage(request, staff_id):

    membership = OrganizationMembership.objects.filter(
        user=request.user,
        role=OrganizationMembership.Role.MANAGER
    ).first()

    if not membership:
        return redirect("dashboard")

    organization = membership.organization

    staff_member = get_object_or_404(
        Staff,
        id=staff_id,
        organization=organization,
        user__isnull=False
    )

    active_assignment = StaffAssignment.objects.filter(
        staff=staff_member,
        is_active=True
    ).select_related(
        "project"
    ).first()

    return render(
        request,
        "staff/staff_manage.html",
        {
            "staff": staff_member,
            "active_assignment": active_assignment,
        }
    )


@login_required
def terminate_project(request, staff_id):

    if request.method != "POST":
        return redirect(
            "staff_manage",
            staff_id=staff_id
        )

    membership = OrganizationMembership.objects.filter(
        user=request.user,
        role=OrganizationMembership.Role.MANAGER
    ).first()

    if not membership:
        return redirect("dashboard")

    organization = membership.organization

    staff_member = get_object_or_404(
        Staff,
        id=staff_id,
        organization=organization,
        user__isnull=False
    )

    active_assignment = StaffAssignment.objects.filter(
        staff=staff_member,
        is_active=True
    ).first()

    if active_assignment:

        active_assignment.is_active = False
        active_assignment.completed_at = timezone.now()

        active_assignment.save(
            update_fields=[
                "is_active",
                "completed_at"
            ]
        )

        staff_member.status = "Available"

        staff_member.save(
            update_fields=["status"]
        )

    return redirect(
        "staff_manage",
        staff_id=staff_member.id
    )


@login_required
def delete_staff(request, staff_id):

    if request.method != "POST":
        return redirect(
            "staff_manage",
            staff_id=staff_id
        )

    membership = OrganizationMembership.objects.filter(
        user=request.user,
        role=OrganizationMembership.Role.MANAGER
    ).first()

    if not membership:
        return redirect("dashboard")

    organization = membership.organization

    staff_member = get_object_or_404(
        Staff,
        id=staff_id,
        organization=organization,
        user__isnull=False
    )

    user = staff_member.user

    user.delete()

    return redirect("staff")

    



@login_required
def staff_view(request, staff_id):

    # ==========================================
    # GET CURRENT MANAGER'S ORGANIZATION
    # ==========================================

    membership = OrganizationMembership.objects.filter(
        user=request.user,
        role=OrganizationMembership.Role.MANAGER
    ).select_related(
        "organization"
    ).first()

    if not membership:
        return redirect("dashboard")

    organization = membership.organization


    # ==========================================
    # GET STAFF MEMBER
    # ==========================================

    staff_member = get_object_or_404(
        Staff,
        id=staff_id,
        organization=organization,
        user__isnull=False
    )


    # ==========================================
    # GET ORGANIZATION MANAGER
    # ==========================================

    manager = OrganizationMembership.objects.filter(
        organization=organization,
        role=OrganizationMembership.Role.MANAGER
    ).select_related(
        "user"
    ).first()


    # ==========================================
    # ACTIVE PROJECT ASSIGNMENTS
    # ==========================================

    active_assignments = StaffAssignment.objects.filter(
        staff=staff_member,
        is_active=True
    ).select_related(
        "project"
    )


    # ==========================================
    # ASSIGNMENT HISTORY
    # ==========================================

    assignment_history = StaffAssignment.objects.filter(
        staff=staff_member
    ).select_related(
        "project"
    ).order_by(
        "-assigned_at"
    )


    # ==========================================
    # RENDER PAGE
    # ==========================================

    return render(
        request,
        "staff/staff_view.html",
        {
            "staff": staff_member,
            "active_assignments": active_assignments,
            "assignment_history": assignment_history,
            "manager": manager,
        }
    )




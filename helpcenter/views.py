import logging

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from .models import ContactMessage

logger = logging.getLogger(__name__)


def contact_submit(request):
    if request.method != "POST":
        return redirect("helpcenter:home")

    name    = request.POST.get("name", "").strip()
    email   = request.POST.get("email", "").strip()
    subject = request.POST.get("subject", "").strip()
    message = request.POST.get("message", "").strip()

    # ── Field-presence validation ─────────────────────────────────────────────
    if not all((name, email, subject, message)):
        messages.error(request, "Please complete all fields before sending your message.")
        return redirect("helpcenter:home")

    # ── Email format validation ───────────────────────────────────────────────
    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, "Please enter a valid email address.")
        return redirect("helpcenter:home")

    # ── Persist to database ───────────────────────────────────────────────────
    ContactMessage.objects.create(
        name=name,
        email=email,
        subject=subject,
        message=message,
    )

    # ── Send support email ────────────────────────────────────────────────────
    # From  → the configured SMTP account (DEFAULT_FROM_EMAIL / EMAIL_HOST_USER)
    # To    → that same support/admin address
    # Reply-To → the visitor's submitted address so replies go straight to them
    from_addr = django_settings.DEFAULT_FROM_EMAIL or django_settings.EMAIL_HOST_USER

    body = (
        f"New support message via the Help Center\n"
        f"{'─' * 46}\n\n"
        f"Name:    {name}\n"
        f"Email:   {email}\n"
        f"Subject: {subject}\n\n"
        f"Message:\n{message}\n"
    )

    try:
        mail = EmailMessage(
            subject=f"[ClientSpace] Support request — {subject}",
            body=body,
            from_email=from_addr,
            to=[from_addr],            # delivered to the support inbox
            reply_to=[email],          # "Reply" in mail client goes to the visitor
        )
        mail.send(fail_silently=False)
    except Exception:
        # Log the full traceback for debugging; never expose it to the user.
        logger.exception(
            "Failed to send contact-support email from %s (subject: %s)",
            email,
            subject,
        )
        messages.error(
            request,
            "Your message was saved but could not be delivered by email right now. "
            "Please try again later or contact your workspace manager directly.",
        )
        return redirect("helpcenter:home")

    messages.success(
        request,
        "Your message has been sent successfully. We'll get back to you soon.",
    )
    return redirect("helpcenter:home")


HELP_CATEGORIES = [
    {
        "key": "getting-started",
        "label": "Getting started",
        "icon": "fa-rocket",
        "description": "Find your way around ClientSpace quickly.",
        "faqs": [
            {
                "question": "What is ClientSpace used for?",
                "answer": "ClientSpace keeps your client work together in one place. Use projects to follow work, tasks to track assignments, notifications to catch updates, and settings to manage your workspace preferences.",
            },
            {
                "question": "What can I see in the sidebar?",
                "answer": "The sidebar is tailored to your role. Managers and staff can see team areas such as clients, staff, reports, and settings. Clients see the project areas shared with them.",
            },
            {
                "question": "How do I get back to the main area?",
                "answer": "Select Dashboard from the sidebar. If you are a client, Projects is your main workspace. The ClientSpace logo also provides a consistent way to recognize the shared layout across pages.",
            },
        ],
    },
    {
        "key": "projects-tasks",
        "label": "Projects & tasks",
        "icon": "fa-folder-open",
        "description": "Manage work, assignments, and progress.",
        "faqs": [
            {
                "question": "Where can I find my projects?",
                "answer": "Open Projects from the sidebar. Managers and staff can review the projects they manage or support. Clients can see the projects connected to their account.",
            },
            {
                "question": "How do assigned tasks work?",
                "answer": "Staff members can open My Tasks to see work assigned to them. Open a task to review its project context and update progress according to the available task controls.",
            },
            {
                "question": "I cannot see a project or task. What should I do?",
                "answer": "First check that you are signed in to the correct account. If the item is still missing, ask the project manager to confirm your client or staff assignment and access.",
            },
        ],
    },
    {
        "key": "notifications",
        "label": "Notifications",
        "icon": "fa-bell",
        "description": "Stay on top of project and team updates.",
        "faqs": [
            {
                "question": "How do I read a notification?",
                "answer": "Select the bell in the top navigation, then choose an item. Unread notifications are highlighted and are marked as read when opened. View all notifications opens your complete notification history.",
            },
            {
                "question": "How do I clear unread notifications?",
                "answer": "Open the notification bell and select Mark all read. The unread badge updates immediately without requiring a page refresh.",
            },
            {
                "question": "Why did the notification badge change?",
                "answer": "The badge shows the number of unread notifications for your account. Opening an unread item or marking all as read reduces that count for your account only.",
            },
        ],
    },
    {
        "key": "account-settings",
        "label": "Account & settings",
        "icon": "fa-user-cog",
        "description": "Keep your profile and workspace preferences current.",
        "faqs": [
            {
                "question": "Where do I update my profile?",
                "answer": "Managers and staff can open Settings from the sidebar to review profile and workspace preferences. Keep your display name and profile picture current so teammates can identify you.",
            },
            {
                "question": "How do I sign out?",
                "answer": "Select the sign-out icon in the top-right navigation. Sign out when using a shared computer or when you have finished your session.",
            },
            {
                "question": "What if my account details are wrong?",
                "answer": "Review the available settings first. For details controlled by your organization, contact your manager or workspace administrator so they can correct the account record.",
            },
        ],
    },
    {
        "key": "troubleshooting",
        "label": "Troubleshooting",
        "icon": "fa-life-ring",
        "description": "Quick checks for common problems.",
        "faqs": [
            {
                "question": "A page looks out of date. What should I try?",
                "answer": "Refresh the page once, then open the item again from the sidebar. If the issue continues, sign out and back in to refresh your session.",
            },
            {
                "question": "I received an access or permission error.",
                "answer": "Access is based on your account role and project assignments. Do not share credentials; ask your manager or workspace administrator to verify the required access.",
            },
            {
                "question": "Who should I contact when I am still stuck?",
                "answer": "Contact your workspace manager with the page you were using, the action you tried, and the approximate time it happened. A screenshot without sensitive information can also help diagnose the issue.",
            },
        ],
    },
]


@login_required
def help_home(request):
    return render(request, "helpcenter/help_home.html", {"help_categories": HELP_CATEGORIES})

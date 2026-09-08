from django.urls import path
from . import views

app_name = "notifications"

urlpatterns = [
    # Click a notification → mark read + redirect to its link
    path("<int:pk>/click/",  views.notification_click, name="click"),

    # Mark all unread as read (POST only)
    path("mark-all-read/",   views.mark_all_read,      name="mark_all_read"),

    # AJAX endpoints — Phase 5
    path("ajax/mark-single-read/<int:pk>/", views.mark_single_read_ajax, name="ajax_mark_single_read"),
    path("ajax/mark-all-read/",             views.mark_all_read_ajax,    name="ajax_mark_all_read"),

    # Full notification history page
    path("",                 views.notification_list,   name="list"),
]

from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    # Organisation-wide progress & reports dashboard
    path("", views.reports_overview, name="overview"),

    # CSV export of whatever the current filters show
    #   /reports/export/?type=projects   (default)
    #   /reports/export/?type=tasks
    path("export/", views.export_csv, name="export_csv"),

    # Detailed report for one project
    path("project/<int:pk>/", views.project_report, name="project_report"),
]

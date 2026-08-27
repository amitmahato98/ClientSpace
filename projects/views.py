from django.contrib.auth.decorators import login_required
from django.shortcuts import render


# =========================================================
# PROJECT DATA
# Temporary hardcoded data
# Later this will come from the database
# =========================================================

PROJECTS = {

    "brand-identity-refresh": {
        "name": "Brand identity refresh",
        "client": "Alden & Co.",
        "deadline": "Sep 2",
        "priority": "High",
        "status": "In Progress",

        "progress": 72,
        "completed_tasks": 8,
        "total_tasks": 12,

        "budget": "18,000",
        "paid": "12,960",
        "remaining": "5,040",
    },

    "marketing-site-rebuild": {
        "name": "Marketing site rebuild",
        "client": "Solene Foods",
        "deadline": "Sep 18",
        "priority": "Medium",
        "status": "At Risk",

        "progress": 38,
        "completed_tasks": 4,
        "total_tasks": 10,

        "budget": "14,000",
        "paid": "5,320",
        "remaining": "8,680",
    },

    "q3-investor-deck": {
        "name": "Q3 investor deck",
        "client": "Verdant Capital",
        "deadline": "Aug 28",
        "priority": "High",
        "status": "In Progress",

        "progress": 94,
        "completed_tasks": 9,
        "total_tasks": 10,

        "budget": "7,500",
        "paid": "7,050",
        "remaining": "450",
    },

    "product-photography": {
        "name": "Product photography",
        "client": "Solene Foods",
        "deadline": "Sep 12",
        "priority": "High",
        "status": "Blocked",

        "progress": 15,
        "completed_tasks": 2,
        "total_tasks": 12,

        "budget": "5,200",
        "paid": "780",
        "remaining": "4,420",
    },

    "office-signage-system": {
        "name": "Office signage system",
        "client": "Alden & Co.",
        "deadline": "Oct 10",
        "priority": "Low",
        "status": "Planning",

        "progress": 8,
        "completed_tasks": 1,
        "total_tasks": 12,

        "budget": "6,400",
        "paid": "510",
        "remaining": "5,890",
    },

    "onboarding-flow-redesign": {
        "name": "Onboarding flow redesign",
        "client": "Halcyon Labs",
        "deadline": "Sep 25",
        "priority": "Medium",
        "status": "In Progress",

        "progress": 55,
        "completed_tasks": 6,
        "total_tasks": 11,

        "budget": "18,000",
        "paid": "9,900",
        "remaining": "8,100",
    },
}


# =========================================================
# PROJECT LIST PAGE
# =========================================================

def project_view(request):
    return render(
        request,
        "projects/projects.html"
    )


# =========================================================
# PROJECT DETAIL PAGE
# =========================================================

def project_detail(request, slug):

    # Find the project using the slug from the URL
    project = PROJECTS.get(slug)

    # If the project does not exist
    if project is None:
        return render(
            request,
            "404.html",
            status=404
        )

    # -----------------------------------------------------
    # Temporary task data
    # -----------------------------------------------------

    tasks = [

        {
            "name": "Kickoff call & requirements",
            "completed": True,
            "initials": "AR",
            "assignee": "Alex",
            "date": "Jul 5",
            "priority": "High",
        },

        {
            "name": "Sitemap & content audit",
            "completed": True,
            "initials": "AR",
            "assignee": "Alex",
            "date": "Jul 12",
            "priority": "",
        },

        {
            "name": "Homepage wireframe",
            "completed": True,
            "initials": "AR",
            "assignee": "Alex",
            "date": "Jul 18",
            "priority": "",
        },

        {
            "name": "Interior page wireframes (5 pages)",
            "completed": True,
            "initials": "SI",
            "assignee": "Sana",
            "date": "Jul 24",
            "priority": "",
        },

        {
            "name": "Client review — round 1",
            "completed": True,
            "initials": "AR",
            "assignee": "Alex",
            "date": "Jul 26",
            "priority": "",
        },

        {
            "name": "Visual design — homepage",
            "completed": True,
            "initials": "SI",
            "assignee": "Sana",
            "date": "Aug 2",
            "priority": "",
        },

        {
            "name": "Visual design — interior pages",
            "completed": True,
            "initials": "SI",
            "assignee": "Sana",
            "date": "Aug 9",
            "priority": "",
        },

        {
            "name": "Client review — round 2",
            "completed": True,
            "initials": "AR",
            "assignee": "Alex",
            "date": "Aug 12",
            "priority": "",
        },

        {
            "name": "Front-end build — homepage",
            "completed": False,
            "initials": "AR",
            "assignee": "Alex",
            "date": "Aug 20",
            "priority": "High",
        },

        {
            "name": "Front-end build — interior pages",
            "completed": False,
            "initials": "AR",
            "assignee": "Alex",
            "date": "Aug 27",
            "priority": "",
        },

        {
            "name": "QA & cross-browser testing",
            "completed": False,
            "initials": "SI",
            "assignee": "Sana",
            "date": "Aug 30",
            "priority": "",
        },

        {
            "name": "Launch & handover to client",
            "completed": False,
            "initials": "AR",
            "assignee": "Alex",
            "date": "Sep 2",
            "priority": "",
        },
    ]

    # -----------------------------------------------------
    # Temporary notes
    # -----------------------------------------------------

    notes = [

        {
            "text": "Client requested a clean and modern visual direction.",
            "author": "Alex",
            "date": "Aug 12",
        },

        {
            "text": "Final homepage design approved by the client.",
            "author": "Sana",
            "date": "Aug 9",
        },
    ]

    # -----------------------------------------------------
    # Temporary payments
    # -----------------------------------------------------

    payments = [

        {
            "description": "Initial project payment",
            "amount": "6,000",
            "date": "Jul 5",
        },

        {
            "description": "Design milestone",
            "amount": "6,960",
            "date": "Aug 12",
        },
    ]

    # -----------------------------------------------------
    # Temporary files
    # -----------------------------------------------------

    files = [

        {
            "name": "Project brief.pdf",
            "size": "2.4 MB",
            "date": "Jul 5",
        },

        {
            "name": "Homepage-final.fig",
            "size": "18.2 MB",
            "date": "Aug 9",
        },

        {
            "name": "Brand-assets.zip",
            "size": "8.7 MB",
            "date": "Aug 12",
        },
    ]

    # -----------------------------------------------------
    # Temporary activity
    # -----------------------------------------------------

    activities = [

        {
            "user": "Alex",
            "description": "completed Client review — round 2",
            "date": "Aug 12",
            "icon": "fas fa-check",
        },

        {
            "user": "Sana",
            "description": "uploaded Homepage-final.fig",
            "date": "Aug 9",
            "icon": "fas fa-upload",
        },

        {
            "user": "Alex",
            "description": "updated project progress",
            "date": "Aug 8",
            "icon": "fas fa-chart-line",
        },
    ]

    # -----------------------------------------------------
    # Send everything to template
    # -----------------------------------------------------

    context = {
        "project": project,
        "tasks": tasks,
        "notes": notes,
        "payments": payments,
        "files": files,
        "activities": activities,
    }

    return render(
        request,
        "projects/projectdetails.html",
        context
    )
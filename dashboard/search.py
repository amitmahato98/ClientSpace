"""
Global Search for ClientSpace

Provides workspace-wide search across Projects, Clients, Staff, and Tasks
with organization isolation and role-based access control.
"""

import logging
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse

from accounts.models import OrganizationMembership
from projects.models import Project, Task

User = get_user_model()
logger = logging.getLogger(__name__)


@login_required
def global_search(request):
    """
    AJAX endpoint for global search across Projects, Clients, Staff, and Tasks.
    
    Respects:
    - Organization isolation (users only see data from their organization)
    - Role-based permissions (Clients have restricted access)
    - Result limits (max 5 per category for dropdown)
    
    Returns JSON with categorized results.
    """
    query = request.GET.get('q', '').strip()
    
    if not query:
        return JsonResponse({
            'projects': [],
            'clients': [],
            'staff': [],
            'tasks': [],
            'query': query,
            'total': 0,
        })
    
    user = request.user
    
    # Get user's organization membership
    membership = OrganizationMembership.objects.filter(user=user).first()
    
    if not membership:
        # User has no organization membership
        return JsonResponse({
            'projects': [],
            'clients': [],
            'staff': [],
            'tasks': [],
            'query': query,
        })
    
    organization = membership.organization
    role = membership.role
    
    # Initialize result containers
    project_results = []
    client_results = []
    staff_results = []
    task_results = []
    
    # ── PROJECT SEARCH ─────────────────────────────────────────────────────
    # All roles can search projects, but with different scopes
    
    if role == OrganizationMembership.Role.MANAGER:
        # Managers see all projects in their organization
        projects = Project.objects.filter(
            organization=organization
        ).filter(
            Q(name__icontains=query) |
            Q(description__icontains=query)
        ).select_related('client', 'created_by')[:5]
        
    elif role == OrganizationMembership.Role.STAFF:
        # Staff see projects they are assigned to
        from staff.models import StaffAssignment, Staff
        
        # Get the Staff profile for this user
        try:
            staff_profile = Staff.objects.get(user=user)
            assigned_project_ids = StaffAssignment.objects.filter(
                staff=staff_profile,
                is_active=True
            ).values_list('project_id', flat=True)
            
            projects = Project.objects.filter(
                id__in=assigned_project_ids,
                organization=organization
            ).filter(
                Q(name__icontains=query) |
                Q(description__icontains=query)
            ).select_related('client', 'created_by')[:5]
        except Staff.DoesNotExist:
            projects = []
        
    elif role == OrganizationMembership.Role.CLIENT:
        # Clients only see their own projects
        projects = Project.objects.filter(
            client=user,
            organization=organization
        ).filter(
            Q(name__icontains=query) |
            Q(description__icontains=query)
        ).select_related('client', 'created_by')[:5]
        
    else:
        projects = []
    
    for project in projects:
        project_results.append({
            'id': project.id,
            'name': project.name,
            'status': project.get_status_display(),
            'client_name': project.client_display_name if hasattr(project, 'client_display_name') else (project.client.get_full_name() if project.client else 'No client'),
            'url': f'/projects/{project.id}/',
        })
    
    # ── CLIENT SEARCH ─────────────────────────────────────────────────────
    # Only Managers and Staff can search clients
    
    if role in [OrganizationMembership.Role.MANAGER, OrganizationMembership.Role.STAFF]:
        client_ids = OrganizationMembership.objects.filter(
            organization=organization,
            role=OrganizationMembership.Role.CLIENT
        ).values_list('user_id', flat=True)
        
        clients = User.objects.filter(
            id__in=client_ids
        ).filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(display_name__icontains=query)
        )[:5]
        
        for client in clients:
            client_results.append({
                'id': client.id,
                'name': client.get_full_name() or client.display_name or client.username,
                'email': client.email,
                'username': client.username,
                'url': f'/clients/?client_id={client.id}',
            })
    
    # ── STAFF SEARCH ─────────────────────────────────────────────────────
    # Only Managers and Staff can search staff members
    
    if role in [OrganizationMembership.Role.MANAGER, OrganizationMembership.Role.STAFF]:
        staff_ids = OrganizationMembership.objects.filter(
            organization=organization,
            role=OrganizationMembership.Role.STAFF
        ).values_list('user_id', flat=True)
        
        staff = User.objects.filter(
            id__in=staff_ids
        ).filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(display_name__icontains=query)
        )[:5]
        
        for staff_member in staff:
            staff_results.append({
                'id': staff_member.id,
                'name': staff_member.get_full_name() or staff_member.display_name or staff_member.username,
                'email': staff_member.email,
                'username': staff_member.username,
                'url': f'/staff/{staff_member.id}/view/',
            })
    
    # ── TASK SEARCH ─────────────────────────────────────────────────────
    # Task access depends on role
    
    if role == OrganizationMembership.Role.MANAGER:
        # Managers see all tasks in their organization
        tasks = Task.objects.filter(
            project__organization=organization
        ).filter(
            Q(title__icontains=query) |
            Q(description__icontains=query) |
            Q(project__name__icontains=query)
        ).select_related('project', 'assigned_to')[:5]
        
    elif role == OrganizationMembership.Role.STAFF:
        # Staff see tasks assigned to them
        tasks = Task.objects.filter(
            assigned_to=user,
            project__organization=organization
        ).filter(
            Q(title__icontains=query) |
            Q(description__icontains=query) |
            Q(project__name__icontains=query)
        ).select_related('project', 'assigned_to')[:5]
        
    elif role == OrganizationMembership.Role.CLIENT:
        # Clients see tasks from their projects
        tasks = Task.objects.filter(
            project__client=user,
            project__organization=organization
        ).filter(
            Q(title__icontains=query) |
            Q(description__icontains=query) |
            Q(project__name__icontains=query)
        ).select_related('project', 'assigned_to')[:5]
        
    else:
        tasks = []
    
    for task in tasks:
        task_results.append({
            'id': task.id,
            'title': task.title,
            'status': task.get_status_display(),
            'project_name': task.project.name,
            'project_id': task.project.id,
            'assigned_to': task.assigned_display_name if hasattr(task, 'assigned_display_name') else (task.assigned_to.get_full_name() if task.assigned_to else 'Unassigned'),
            'url': f'/projects/{task.project.id}/#task-{task.id}',
        })
    
    return JsonResponse({
        'projects': project_results,
        'clients': client_results,
        'staff': staff_results,
        'tasks': task_results,
        'query': query,
        'total': len(project_results) + len(client_results) + len(staff_results) + len(task_results),
    })

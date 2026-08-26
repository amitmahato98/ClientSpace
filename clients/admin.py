from django.contrib import admin
from .models import Client, Project, Payment, Note, ClientActivity

admin.site.register(Client)
admin.site.register(Project)
admin.site.register(Payment)
admin.site.register(Note)
admin.site.register(ClientActivity)
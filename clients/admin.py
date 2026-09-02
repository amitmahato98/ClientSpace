from django.contrib import admin
from .models import Payment, Note, ClientActivity

admin.site.register(Payment)
admin.site.register(Note)
admin.site.register(ClientActivity)
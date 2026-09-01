from django.urls import path
from staff import views

urlpatterns=[
    path('staff/',views.staff,name='staff'),
    path('add_staff/',views.add_staff,name='add_satff'),
]
from django.urls import path

from . import views

urlpatterns = [
    path("public/csat/<str:token>/", views.submit_csat, name="csat-submit"),
]

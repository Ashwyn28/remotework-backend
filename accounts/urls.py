from django.urls import path

from . import views

urlpatterns = [
    path("auth/config/", views.config),
    path("auth/google/", views.google_sign_in),
    path("auth/sign-out/", views.sign_out),
    path("me/", views.me),
]

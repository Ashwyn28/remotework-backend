from django.urls import path
from work import views

urlpatterns = [
    path("listing/", views.create_listing),
    path("listings/", views.Listings.as_view()),
    path("create-checkout-session/", views.create_checkout_session),
]

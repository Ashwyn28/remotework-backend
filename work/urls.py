from django.urls import path
from work import views

urlpatterns = [
    path("create/", views.create_listing),
    path("listings/", views.Listings.as_view()),
    path("pay/", views.create_checkout_session),
    path("elements/", views.create_payment_intent),
]

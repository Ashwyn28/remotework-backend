from django.urls import path
from work import views

urlpatterns = [
    path("create/", views.create_listing),
    path("listings/", views.Listings.as_view()),
    path("elements/", views.PayListing.as_view()),
    path("success/", views.SetListingSuccessful.as_view())
]

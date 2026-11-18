from django.urls import path

from work import views

urlpatterns = [
    path("create/", views.ListingView.as_view({"post": "create"})),
    path("listings/", views.Listings.as_view()),
    path("board/", views.Board.as_view()),
    path("elements/", views.PayListing.as_view()),
    path("success/", views.SetListingSuccessful.as_view()),
    path("companies/", views.Companies.as_view()),
    path("auth/", views.Auth.as_view()),
    path("user/", views._User.as_view()),
]

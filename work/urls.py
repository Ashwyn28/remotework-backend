from django.urls import path
from work import views

urlpatterns = [
    path('listing/', views.create_listing),
    path('listings/', views.Listings.as_view()),
    path('category/', views.ListingsCategory.as_view()),
    # path('premium/', views.ListingsPremium.as_view({'get': 'list'}))
]
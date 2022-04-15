from django.shortcuts import redirect
from rest_framework import viewsets, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from work.serialisers import ListingSerializer
from work.models import Listing
from dotenv import load_dotenv
import os
import stripe

load_dotenv()
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")
stripe.api_key = STRIPE_API_KEY

# Map all api routes
#   -> get all premium listings
#   -> shuffle listings with premiums at the top
#   -> route to send payment info to stripe

# todo: method to set listing as premium
# ? once a purchase has been completed


class PremiumListingPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = "page_size"
    max_page_size = 5


class ListingsPremium(viewsets.ReadOnlyModelViewSet):
    # add pagination
    queryset = Listing.objects.filter(premium=True)
    pagination_class = PremiumListingPagination
    serializer_class = ListingSerializer


class Listings(ListAPIView):
    # add pagination
    serializer_class = ListingSerializer

    def get_queryset(self):
        category = self.request.query_params.get("category")
        queryset = Listing.objects.all()
        if category is not None:
            queryset = queryset.filter(category=category)
        return queryset


@api_view(["POST"])
def create_listing(request):
    """
    Create a new listing
    """
    serializer = ListingSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
def create_checkout_session(request):
    session = stripe.checkout.Session.create(
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": "T-shirt",
                    },
                    "unit_amount": 2000,
                },
                "quantity": 1,
            }
        ],
        mode="payment",
        success_url="http://localhost:3000/pay/success",
        cancel_url="https://example.com/cancel",
    )

    return redirect(session.url, code=303)

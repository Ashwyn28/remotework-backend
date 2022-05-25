from django.shortcuts import redirect
from django.http import JsonResponse
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

class Filters(ListAPIView):
    # TODO: query all unique categories
    # -> frontend should make the api call and populate
    #   the filters component

    # add pagination
    serializer_class = ListingSerializer

    def get_queryset(self):
        queryset = Listing.objects.get(category)
        return queryset

class Companies(ListAPIView):
    # TODO: annotate/group all listings by company_name

    pass

@api_view(["POST"])
def create_checkout_session(request):
    session = stripe.checkout.Session.create(
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": "Listing",
                    },
                    "unit_amount": 19900,
                },
                "quantity": 1,
            }
        ],
        mode="payment",
        success_url="http://localhost:3000/pay/success",
        cancel_url="https://example.com/cancel",
    )

    return redirect(session.url, code=303)


def calculate_order_amount(items):
    breakpoint()
    return 1400

@api_view(["POST"])
def create_payment_intent(request):
    """
    Create custom payment form
    """
    try:
        data = request.data
        # Create a PaymentIntent with the order amount and currency
        intent = stripe.PaymentIntent.create(
            amount=calculate_order_amount(data['items']),
            currency='eur',
            automatic_payment_methods={
                'enabled': True,
            },
        )
        return JsonResponse({
            'clientSecret': intent['client_secret']
        })
    except Exception as e:
        return JsonResponse(error=str(e)), 403

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
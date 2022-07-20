from django.http import JsonResponse
from rest_framework import viewsets, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.generics import ListAPIView
from rest_framework.views import APIView
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
        pk = self.request.query_params.get("pk")
        state = self.request.query_params.get("state")

        queryset = Listing.objects.all()
        
        if category is not None:
            queryset = queryset.filter(category=category)
        if pk is not None:
            queryset = queryset.filter(pk=pk)
        if state == 'paid':
            queryset = queryset.filter(paid=True)
        if state == 'in_progress':
            queryset = queryset.filter(in_progress=True)
        if state == 'failed':
            queryset = queryset.filter(failed=True)
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
    serializer_class = ListingSerializer

    def get_queryset(self):
        queryset = Listing.objects.get(company_name)
        # -> grab all listings with
        return queryset

def calculate_order_amount(items):
    for item in items:
        if item["id"] == "basic":
            return 1400
        if item["id"] == "premium":
            return 2000


@api_view(["POST"])
def create_payment_intent(request):
    """
    Create custom payment form
    """
    try:
        data = request.data
        # Create a PaymentIntent with the order amount and currency
        intent = stripe.PaymentIntent.create(
            amount=calculate_order_amount(data["items"]),
            currency="eur",
            automatic_payment_methods={
                "enabled": True,
            },
        )
        return JsonResponse({"clientSecret": intent["client_secret"]})
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


class PayListing(APIView):
    def post(self, request):
        payment = create_payment_intent(self.request)
        # set listing to paid for
        listing_id = request.query_params.get("pk")
        if listing_id:
            Listing.objects.filter(id=listing_id).update(in_progress=True)
        return payment

    def dispatch(self, request):
        request = self.initialize_request(request)
        response = self.post(request)
        return response


class SetListingSuccessful(APIView):
    def post(self, request):
        listing_id = request.query_params.get("pk")
        if listing_id:
            listing = Listing.objects.filter(id=listing_id).update(paid=True)
        return Response(listing)

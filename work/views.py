import json
import logging
import os

import stripe
from django.contrib.auth.models import User
from django.http import JsonResponse
from dotenv import load_dotenv
from google.auth.transport import requests
from google.oauth2 import id_token
from rest_framework import status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from work import serialisers
from work.models import Company, Listing
from work.serialisers import (CompanySerializer, ListingSerializer,
                              UserSerializer)

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
    permission_classes = [AllowAny]


class Listings(ListAPIView):
    # add pagination
    serializer_class = ListingSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        category = self.request.query_params.get("category")
        pk = self.request.query_params.get("pk")
        state = self.request.query_params.get("state")

        queryset = Listing.objects.all()
        if category is not None:
            queryset = queryset.filter(category=category)
        if pk is not None:
            queryset = queryset.filter(pk=pk)
        if state == "paid":
            queryset = queryset.filter(paid=True)
        if state == "in_progress":
            queryset = queryset.filter(in_progress=True)
        if state == "failed":
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
    serializer_class = CompanySerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = Company.objects.prefetch_related("listings")
        return queryset

def calculate_order_amount(items):
    for item in items:
        if item["id"] == "basic":
            return 1400
        if item["id"] == "premium":
            return 2000


class ListingView(viewsets.ModelViewSet):
    queryset = Listing.objects.all()
    serializer_class = ListingSerializer
    permission_classes = [AllowAny]


class PayListing(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
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
            payment = JsonResponse({"clientSecret": intent["client_secret"]})
        except Exception as e:
            payment = JsonResponse(error=str(e)), 403
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
    permission_classes = [AllowAny]

    def post(self, request):
        listing_id = request.query_params.get("pk")
        if listing_id:
            listing = Listing.objects.filter(id=listing_id).update(paid=True)
        return Response(listing)


class Auth(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = json.loads(request.body)
        token = data
        # verify token
        try:
            idinfo = id_token.verify_oauth2_token(
                token,
                requests.Request(),
                "601837645469-i46geu02ca7rthamniuehgkp5ithjbl9.apps.googleusercontent.com",
            )

            if idinfo:
                auth_data = {
                    "first_name": idinfo["name"],
                    "email": idinfo["email"],
                }

        except ValueError:
            logging.error("Invalid token")

        serializer = serialisers.UserSerializer(data=auth_data)

        user = User.objects.filter(email=auth_data["email"])
        if user.exists():
            token = Token.objects.get_or_create(user=user.first())
            data = {
                "id": user.first().id,
                "our_token": token[0].key,
                "first_name": auth_data["first_name"],
                "email": auth_data["email"],
            }
            # need to update to use correct status code
            return Response(data, status=status.HTTP_200_OK)

        if not user.exists():
            # redirect to enter company details
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class _User(ListAPIView):

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user_id = self.request.query_params.get("pk")
        if user_id:
            user = User.objects.filter(id=user_id)
        return user

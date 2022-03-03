from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework import permissions
from work.serialisers import ListingSerializer
from work.models import Listing

# Map all api routes 
#   -> get all premium listings
#   -> shuffle listings with premiums at the top
#   -> route to send payment info to stripe 

class PremiumListingPagination(PageNumberPagination):
    page_size = 4
    page_size_query_param = 'page_size'
    max_page_size = 4
    
class ListingsPremium(viewsets.ReadOnlyModelViewSet):
    # add pagination
    queryset = Listing.objects.filter(premium=True)
    pagination_class = PremiumListingPagination
    serializer_class = ListingSerializer

class Listings(ListAPIView):
    # add pagination
    serializer_class = ListingSerializer
    def get_queryset(self):
        category = self.request.query_params.get('category')
        queryset = Listing.objects.all()
        if category is not None:
            queryset = queryset.filter(category=category)
        return queryset

@api_view(['POST'])
def create_listing(request):
    """
    Create a new listing
    """
    serializer = ListingSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ListingsCategory(ListAPIView):
    serializer_class = ListingSerializer
    
    def get_queryset(self):
        category = self.request.query_params.get('category')
        queryset = Listing.objects.all()
        if category is not None:
            queryset = queryset.filter(category=category)
        return queryset




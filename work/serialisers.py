from rest_framework import serializers
from .models import Listing

class ListingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Listing
        fields = [
        'id',
        'company_name', 
        'job_title',
        'description', 
        'category', 
        'salary', 
        'region', 
        'is_verified', 
        'premium', 
        'profile_url',
        'application_url'
    ]

class FullListingSerialiser(ListingSerializer):
    class Meta:
        model = Listing
        fields = [
            'paid',
            'failed'
        ]
            
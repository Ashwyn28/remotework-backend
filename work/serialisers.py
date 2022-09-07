from django.contrib.auth.models import User
from rest_framework import serializers

from work.models import Company, Listing


class CompanyNameSerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["name"]


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["first_name", "email"]


class ListingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Listing
        fields = [
            "id",
            "company",
            "job_title",
            "description",
            "category",
            "salary",
            "region",
            "premium",
            "application_url",
        ]


class FullListingSerializer(ListingSerializer):
    paid = serializers.BooleanField()
    in_progess = serializers.BooleanField()
    failed = serializers.BooleanField()


class CompanySerializer(serializers.ModelSerializer):
    listings = ListingSerializer(many=True)

    class Meta:
        model = Company
        fields = [
            "name",
            "description",
            "category",
            "is_verified",
            "profile_url",
            "listings",
        ]

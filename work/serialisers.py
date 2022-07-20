from rest_framework import serializers
from .models import Company


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["name", "category", "is_verified", "profile_url"]


class ListingSerializer(serializers.Serializer):
    company = CompanySerializer(required=True)
    job_title = serializers.CharField(required=True)
    description = serializers.CharField(required=True)
    category = serializers.CharField(required=True)
    salary = serializers.IntegerField(required=True)
    region = serializers.CharField(required=True)
    premium = serializers.BooleanField(required=True)
    application_url = serializers.URLField(required=True)


class FullListingSerializer(ListingSerializer):
    paid = serializers.BooleanField()
    in_progess = serializers.BooleanField()
    failed = serializers.BooleanField()

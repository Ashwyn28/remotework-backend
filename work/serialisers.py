from django.contrib.auth.models import User
from django.templatetags.static import static
from rest_framework import serializers

from work.logos import logo_filename
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
            "arrangement",
            "premium",
            "application_url",
            "posted_at",
            "verified_at",
            "seniority",
        ]
        read_only_fields = ["posted_at", "verified_at", "seniority"]


class BoardCompanySerializer(serializers.ModelSerializer):
    # path of the downloaded logo on this site ("/static/logos/…"), or the company's own
    # image URL, or null. A path rather than a full URL, because the API is reached through
    # the site's own origin: the same path works in development and production.
    logo = serializers.SerializerMethodField()

    def get_logo(self, company):
        filename = logo_filename(company)
        if filename:
            return static(f"logos/{filename}")
        return company.profile_url or None

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "description",
            "industry",
            "location",
            "size",
            "rank",
            "is_top",
            "is_verified",
            "profile_url",
            "logo",
            "stage",
            "founded",
            "funding",
            "mission",
            "investors",
            "perks",
            "website",
        ]


class BoardListingSerializer(ListingSerializer):
    """A listing with its company nested, as the job board displays it."""

    company = BoardCompanySerializer(read_only=True)


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

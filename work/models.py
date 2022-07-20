from django.db import models
from django.forms import ModelForm


class Filters(models.Model):
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=255)


class Company(models.Model):
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255)
    category = models.CharField(max_length=255)
    is_verified = models.BooleanField(default=False)
    profile_url = models.URLField(null=True, max_length=500)


class Listing(models.Model):
    company = models.ForeignKey(
        Company, on_delete=models.PROTECT, null=False, default=None
    )
    job_title = models.CharField(max_length=255)
    description = models.TextField(null=True)
    category = models.CharField(max_length=255)
    salary = models.IntegerField(null=True)
    region = models.CharField(max_length=255)
    application_url = models.URLField(null=True, max_length=500)
    premium = models.BooleanField(default=False)
    created = models.BooleanField(default=False)
    in_progress = models.BooleanField(default=False)
    paid = models.BooleanField(default=False)
    failed = models.BooleanField(default=False)

    def create(self, validated_data):
        """
        Create and validate a new Listing
        """
        return Listing.objects.create(**validated_data)


class ListingForm(ModelForm):
    class Meta:
        model = Listing
        fields = "__all__"

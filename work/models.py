from django.db import models
from django.forms import ModelForm


class Filters(models.Model):
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=255)


# TODO: fix company and listing models relations!!!
class Company(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField()
    description = models.CharField(null=True, max_length=255, default=None)
    category = models.CharField(null=True, max_length=255, default=None)
    is_verified = models.BooleanField(null=True, default=False)
    profile_url = models.URLField(null=True, max_length=500, default=None)
    # size - number of people
    # location - where is the company based at / remote
    # sector - what sector does it operate in
    def create(self, validated_data):
        """
        Create and validate a new company
        """
        return Company.objects.create(**validated_data)


class Listing(models.Model):
    company = models.ForeignKey(
        Company,
        related_name="listings",
        on_delete=models.PROTECT,
        null=False,
        default=None,
    )
    job_title = models.CharField(max_length=255)
    description = models.TextField(null=True)
    category = models.CharField(max_length=255)
    salary = models.IntegerField(null=True)
    region = models.CharField(max_length=255)
    application_url = models.URLField(null=True, max_length=500)
    # years of experience required
    # tags [tags e.g tech stack good to add fitlers to]
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

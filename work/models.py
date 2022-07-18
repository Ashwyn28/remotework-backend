from django.db import models
from django.forms import ModelForm


class Filters(models.Model):
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=255)


# todo: handle payment states
# -> should have the following states
#  [pending, complete]
# -> data should be stored in frontend store
# -> payment should then be processed
# -> should obtain a success event from stripe then create the listing
# follow docs https://stripe.com/docs/payments/checkout/fulfill-orders

# use celery to manage creation and payment for listing

# we want to use a model which is based off of the listing model
class Listing(models.Model):
    company_name = models.CharField(max_length=255)
    job_title = models.CharField(max_length=255)
    description = models.TextField(null=True)
    category = models.CharField(max_length=255)
    salary = models.IntegerField(null=True)
    region = models.CharField(max_length=255)
    is_verified = models.BooleanField(default=False)
    premium = models.BooleanField(default=False)
    profile_url = models.URLField(null=True, max_length=500)
    application_url = models.URLField(null=True, max_length=500)
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

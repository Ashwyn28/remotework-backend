from django.db import models
from django.forms import ModelForm

class Filters(models.Model):
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=255)

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
    profile_url = models.URLField(null=True)
    profile_image = models.ImageField(upload_to='profile_images', null=True)

    def create(self, validated_data):
        """
        Create and validate a new Listing
        """
        return Listing.objects.create(**validated_data)
    
class ListingForm(ModelForm):
    class Meta:
        model = Listing
        fields = '__all__'

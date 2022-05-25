import json
import factory
from factory.django import DjangoModelFactory

from .models import Listing

class ListingFactory(DjangoModelFactory):
    class Meta:
        model = Listing

    company_name = factory.Faker('name')
    job_title = factory.Faker('job')
    description = factory.Faker('sentence', nb_words=10)
    category = factory.Faker('sentence', nb_words=1)
    salary = factory.Faker('credit_card_number')
    region = factory.Faker('city')
    is_verified = factory.Faker('boolean')
    premium = factory.Faker('boolean')
    application_url = factory.Faker('sentence', nb_words=10)    


# listing = json.dumps(ListingFactory())

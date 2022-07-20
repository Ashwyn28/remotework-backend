import json
import factory
from factory.django import DjangoModelFactory

from .models import Company, Listing

class CompanyFactory(DjangoModelFactory):
    class Meta:
        model = Company
    
    name = factory.Faker('name')
    description = factory.Faker('sentence', nb_words=30)
    category = factory.Faker('sentence', nb_words=1)
    is_verified = factory.Faker('boolean')
    profile_url = factory.Faker('url')
    
class ListingFactory(DjangoModelFactory):
    class Meta:
        model = Listing

    company = CompanyFactory()
    job_title = factory.Faker('job')
    description = factory.Faker('sentence', nb_words=10)
    category = factory.Faker('sentence', nb_words=1)
    salary = factory.Faker('credit_card_number')
    region = factory.Faker('city')
    premium = factory.Faker('boolean')
    application_url = factory.Faker('sentence', nb_words=10)    


# listing = json.dumps(ListingFactory())

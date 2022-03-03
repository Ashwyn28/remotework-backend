from lib2to3.pytree import Base
from django.core.management.base import BaseCommand

from work.models import Listing
from work.factories import ListingFactory

NUM_LISTING = 10

class Command(BaseCommand):
    help = "Generates test data"
    
    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Creating new data")
        for _ in range(NUM_LISTING):
            Listing.create(ListingFactory())
        
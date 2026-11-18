import json
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from work.models import Company, Listing

SEED_FILE = Path(__file__).resolve().parents[2] / "seed" / "board.json"


class Command(BaseCommand):
    help = (
        "Load the sample job board (fictional top companies and their listings). "
        "Safe to run more than once; existing rows are updated, nothing is deleted."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        companies = json.loads(SEED_FILE.read_text())
        rank_by_industry = {}
        listings = 0
        now = timezone.now()
        for data in companies:
            # companies are listed best-first within each industry
            industry = data["industry"]
            rank = rank_by_industry[industry] = rank_by_industry.get(industry, 0) + 1
            company, _ = Company.objects.update_or_create(
                name=data["name"],
                defaults={
                    "email": f"jobs@{slugify(data['name'])}.example",
                    "description": data["description"],
                    "category": industry,
                    "industry": industry,
                    "location": data["location"],
                    "size": data["size"],
                    "is_verified": True,
                    "is_top": True,
                    "rank": rank,
                    "stage": data.get("stage", ""),
                    "founded": data.get("founded"),
                    "funding": data.get("funding", ""),
                    "mission": data.get("mission", ""),
                    "investors": ", ".join(data.get("investors", [])),
                    "perks": "\n".join(data.get("perks", [])),
                },
            )
            for position, listing in enumerate(data["listings"]):
                Listing.objects.update_or_create(
                    company=company,
                    job_title=listing["job_title"],
                    defaults={
                        "description": listing["description"],
                        "category": listing["category"],
                        "salary": listing["salary"],
                        "arrangement": listing["arrangement"],
                        "region": data["location"],
                        # the first listing is the company's headline role
                        "premium": position == 0,
                        # spread sample dates so the board shows a realistic mix
                        "posted_at": now - timedelta(days=1 + (listings * 5) % 23),
                        "verified_at": (now - timedelta(days=listings % 6)).date(),
                    },
                )
                listings += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(companies)} top companies and {listings} listings."
            )
        )

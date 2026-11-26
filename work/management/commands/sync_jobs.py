import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from work.jobsources.sync import sync
from work.logos import ensure_logo, logo_filename
from work.models import Company

# shared with the sync Lambda
COMPANIES = Path(__file__).resolve().parents[3] / "jobfeed" / "companies.json"


class Command(BaseCommand):
    help = (
        "Register the curated companies in jobfeed/companies.json and import their open UK roles "
        "from their public careers sites (Greenhouse, Lever, Ashby). Safe to run repeatedly: roles "
        "are updated in place and roles a company no longer lists are removed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            nargs="+",
            metavar="NAME",
            help="sync just these companies, by name",
        )
        parser.add_argument(
            "--hide-others",
            action="store_true",
            help="take every company not in the curated list off the board (is_top=False); deletes nothing",
        )

    def handle(self, *args, **options):
        try:
            curated = json.loads(COMPANIES.read_text())
        except (OSError, ValueError) as error:
            raise CommandError(f"Cannot read {COMPANIES}: {error}") from error

        # companies without a usable feed are only linked to on the board, not synced here
        curated = [entry for entry in curated if entry.get("ats") != "link"]
        companies = self.register(curated)
        self.add_missing_logos(companies)
        if options["hide_others"]:
            hidden = Company.objects.exclude(pk__in=[c.pk for c in companies]).update(is_top=False)
            self.stdout.write(f"Took {hidden} other companies off the board.")

        if options["only"]:
            wanted = {name.lower() for name in options["only"]}
            companies = [c for c in companies if c.name.lower() in wanted]
            if not companies:
                raise CommandError("None of those names are in the curated list.")

        result = sync(companies)
        self.stdout.write(
            self.style.SUCCESS(
                f"{result.created} new, {result.updated} updated, {result.removed} removed; "
                f"{result.skipped} roles outside the UK skipped."
            )
        )
        if result.failed:
            self.stdout.write(self.style.WARNING(f"Could not reach: {', '.join(result.failed)}. Their roles were kept."))

    def add_missing_logos(self, companies):
        """Every board company shows its logo, so fetch any that are missing."""
        for company in companies:
            if logo_filename(company):
                continue
            if not company.website:
                self.stdout.write(self.style.WARNING(f"{company.name} has no website, so it has no logo."))
                continue
            source = ensure_logo(company)
            if source:
                self.stdout.write(f"Logo for {company.name}: {source}")
            else:
                self.stdout.write(self.style.WARNING(f"No logo found for {company.name}; showing initials."))

    @transaction.atomic
    def register(self, curated):
        companies = []
        rank_by_industry = {}
        for entry in curated:
            if not entry.get("website"):
                raise CommandError(f"{entry['name']} needs a website in companies.json, for its logo.")
            industry = entry["industry"]
            rank = rank_by_industry[industry] = rank_by_industry.get(industry, 0) + 1
            company, _ = Company.objects.update_or_create(
                name=entry["name"],
                defaults={
                    "email": f"careers@{slugify(entry['name'])}.invalid",
                    "industry": industry,
                    "location": entry.get("location", ""),
                    "description": entry.get("description", "")[:255],
                    "stage": entry.get("stage", ""),
                    "website": entry.get("website", ""),
                    "ats": entry["ats"],
                    "ats_slug": entry["board"],
                    "is_top": True,
                    "rank": rank,
                },
            )
            companies.append(company)
        return companies

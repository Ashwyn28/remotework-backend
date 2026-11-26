from django.core.management.base import BaseCommand

from work.logos import ensure_logo, logo_filename
from work.models import Company


class Command(BaseCommand):
    help = (
        "Download a logo for every company with a website into work/static/logos/. "
        "sync_jobs and the admin already do this for new companies; use --force to refresh."
    )

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="replace logos already downloaded")

    def handle(self, *args, **options):
        saved = skipped = failed = 0
        for company in Company.objects.exclude(website=""):
            if logo_filename(company) and not options["force"]:
                skipped += 1
                continue
            source = ensure_logo(company, force=options["force"])
            if source:
                self.stdout.write(f"{company.name}: {source}")
                saved += 1
            else:
                self.stdout.write(self.style.WARNING(f"{company.name}: no usable logo found"))
                failed += 1
        self.stdout.write(self.style.SUCCESS(f"{saved} saved, {skipped} already had one, {failed} not found."))

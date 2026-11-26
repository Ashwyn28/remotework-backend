from django.db import models
from django.forms import ModelForm
from django.utils import timezone


class Filters(models.Model):
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=255)


# TODO: fix company and listing models relations!!!
class Company(models.Model):
    STAGES = [
        ("seed", "Seed"),
        ("series-a", "Series A"),
        ("series-b", "Series B"),
        ("series-c-plus", "Series C+"),
        ("bootstrapped", "Bootstrapped"),
        ("public", "Public"),
    ]

    name = models.CharField(max_length=255)
    email = models.EmailField()
    description = models.CharField(null=True, blank=True, max_length=255, default=None)
    category = models.CharField(null=True, blank=True, max_length=255, default=None)
    is_verified = models.BooleanField(null=True, default=False)
    profile_url = models.URLField(null=True, blank=True, max_length=500, default=None)
    # slug of the industry the company operates in, e.g. "fintech"
    industry = models.SlugField(max_length=64, blank=True, default="")
    location = models.CharField(max_length=255, blank=True, default="")
    # free text, e.g. "220 people"
    size = models.CharField(max_length=64, blank=True, default="")
    # only top companies are shown on the job board
    is_top = models.BooleanField(default=False)
    # position within the company's industry; lower is better
    rank = models.PositiveIntegerField(null=True, blank=True)

    # profile shown on the company page
    stage = models.CharField(max_length=32, choices=STAGES, blank=True, default="")
    founded = models.PositiveSmallIntegerField(null=True, blank=True)
    # free text, e.g. "£40m raised"
    funding = models.CharField(max_length=100, blank=True, default="")
    # one sentence on why the company exists
    mission = models.TextField(blank=True, default="")
    # comma-separated
    investors = models.TextField(blank=True, default="")
    # one perk per line
    perks = models.TextField(blank=True, default="")
    website = models.URLField(max_length=500, blank=True, default="")

    # where the company publishes its open roles; synced by `manage.py sync_jobs`
    ATS_CHOICES = [
        ("greenhouse", "Greenhouse"),
        ("lever", "Lever"),
        ("ashby", "Ashby"),
    ]
    ats = models.CharField(max_length=16, choices=ATS_CHOICES, blank=True, default="")
    # the company's board name on that system, e.g. "monzo"
    ats_slug = models.CharField(max_length=100, blank=True, default="")
    last_synced_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name

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
    # slug of the type of work, e.g. "engineering"
    category = models.CharField(max_length=255)
    # free text so ranges and currencies fit, e.g. "£85k – £105k"
    salary = models.CharField(max_length=100, null=True, blank=True)
    region = models.CharField(max_length=255)
    # e.g. "Hybrid", "On-site", "Remote (UK)"
    arrangement = models.CharField(max_length=64, blank=True, default="")
    posted_at = models.DateTimeField(default=timezone.now)
    # last date the employer confirmed the role is still open
    verified_at = models.DateField(null=True, blank=True)
    application_url = models.URLField(null=True, max_length=500)
    # "<ats>:<board>:<job id>" for roles imported from a careers site; empty for posted roles
    source_id = models.CharField(max_length=200, null=True, blank=True, unique=True, default=None)
    SENIORITY_CHOICES = [
        ("junior", "Junior"),
        ("mid", "Mid-level"),
        ("senior", "Senior"),
        ("staff", "Staff and principal"),
        ("manager", "Manager and above"),
    ]
    seniority = models.CharField(max_length=16, choices=SENIORITY_CHOICES, blank=True, default="")
    # years of experience required
    # tags [tags e.g tech stack good to add fitlers to]
    premium = models.BooleanField(default=False)
    created = models.BooleanField(default=False)
    in_progress = models.BooleanField(default=False)
    paid = models.BooleanField(default=False)
    failed = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.job_title} ({self.company})"

    def create(self, validated_data):
        """
        Create and validate a new Listing
        """
        return Listing.objects.create(**validated_data)


class ListingForm(ModelForm):
    class Meta:
        model = Listing
        fields = "__all__"

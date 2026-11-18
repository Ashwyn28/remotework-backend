from django.contrib import admin, messages

from .logos import ensure_logo, logo_filename
from .models import Company, Listing


class ListingInline(admin.TabularInline):
    model = Listing
    extra = 0
    fields = ["job_title", "category", "salary", "arrangement", "region", "premium"]


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    # is_top and rank decide what the job board shows, so they are editable in the list
    list_display = ["name", "has_logo", "industry", "stage", "is_top", "rank", "location", "size"]
    list_editable = ["is_top", "rank"]
    list_filter = ["is_top", "industry", "stage"]
    search_fields = ["name"]
    inlines = [ListingInline]
    actions = ["refresh_logos"]

    @admin.display(boolean=True, description="Logo")
    def has_logo(self, company):
        return logo_filename(company) is not None

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # every company shows its logo: fetch one for new companies and changed websites
        if obj.website and (not change or "website" in form.changed_data or not logo_filename(obj)):
            if ensure_logo(obj, force="website" in form.changed_data):
                self.message_user(request, f"Fetched the logo for {obj.name}.")
            elif not logo_filename(obj):
                self.message_user(
                    request, f"Could not find a logo for {obj.name}; the board shows its initials.", messages.WARNING
                )

    @admin.action(description="Refresh logos from their websites")
    def refresh_logos(self, request, queryset):
        fetched = sum(1 for company in queryset if ensure_logo(company, force=True))
        self.message_user(request, f"Refreshed {fetched} of {queryset.count()} logos.")


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = [
        "job_title",
        "company",
        "category",
        "salary",
        "premium",
        "posted_at",
        "verified_at",
    ]
    list_editable = ["verified_at"]
    list_filter = ["premium", "category", "company__industry"]
    search_fields = ["job_title", "company__name"]

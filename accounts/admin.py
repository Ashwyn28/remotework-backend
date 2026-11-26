from django.contrib import admin

from .models import SeekerProfile


@admin.register(SeekerProfile)
class SeekerProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "created_at", "updated_at"]
    search_fields = ["user__email"]
    readonly_fields = ["google_sub", "created_at", "updated_at"]

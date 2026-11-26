from django.conf import settings
from django.db import models


class SeekerProfile(models.Model):
    """A job seeker who signed in with Google, and the answers and saved roles they keep in sync."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="seeker")
    # Google's stable account ID ("sub"); email addresses can change, this cannot
    google_sub = models.CharField(max_length=255, unique=True)
    # the onboarding answers, in the shape the frontend uses (validated on save)
    preferences = models.JSONField(default=dict, blank=True)
    # job id -> {"status": "saved" | "applied", "at": epoch ms}
    tracked = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.user.email or self.google_sub

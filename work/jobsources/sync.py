"""Bring the board's listings in line with each company's careers site."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from work.models import Company, Listing

from . import Role, SourceError, classify, fetch

log = logging.getLogger(__name__)


@dataclass
class Result:
    created: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0  # roles outside the UK
    failed: list[str] = field(default_factory=list)


def listing_fields(role: Role) -> dict:
    return {
        "job_title": role.title[:255],
        "description": role.description,
        "category": classify.work_type(role.title, role.department),
        "seniority": classify.seniority(role.title),
        "salary": role.salary[:100],
        "region": role.location[:255],
        "arrangement": classify.arrangement(role),
        "application_url": role.apply_url or role.url,
        "posted_at": role.posted_at or timezone.now(),
        # it is listed on the employer's own site right now, so it is open
        "verified_at": timezone.localdate(),
    }


def sync_company(company: Company, roles: list[Role], result: Result) -> None:
    """Upsert the company's UK roles and remove imported roles it no longer lists."""
    seen: set[str] = set()
    with transaction.atomic():
        for role in roles:
            if not role.title or not (role.apply_url or role.url):
                continue
            if not classify.is_uk(role):
                result.skipped += 1
                continue
            seen.add(role.source_id)
            _, created = Listing.objects.update_or_create(
                source_id=role.source_id,
                defaults={"company": company, **listing_fields(role)},
            )
            if created:
                result.created += 1
            else:
                result.updated += 1
        stale = Listing.objects.filter(company=company, source_id__startswith=f"{company.ats}:").exclude(
            source_id__in=seen
        )
        result.removed += stale.count()
        stale.delete()
        company.last_synced_at = timezone.now()
        company.save(update_fields=["last_synced_at"])


def sync(companies) -> Result:
    result = Result()
    for company in companies:
        try:
            roles = fetch(company.ats, company.ats_slug)
        except SourceError as error:
            # keep yesterday's roles rather than emptying the company on a temporary outage
            log.warning("Could not read %s: %s", company.name, error)
            result.failed.append(company.name)
            continue
        sync_company(company, roles, result)
    return result

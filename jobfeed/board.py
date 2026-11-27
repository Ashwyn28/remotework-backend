"""Build the board: every open UK role at the curated companies, as one JSON file.

The site reads `data/board.json`; logos sit beside it under `static/logos/`. Running this
again replaces the file: new roles appear, closed roles disappear. A company whose careers
site cannot be reached keeps yesterday's roles rather than vanishing from the board.
"""
from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import classify
from .logos import CONTENT_TYPES, find_logo, slugify
from .sources import Role, SourceError, fetch
from .storage import Store

log = logging.getLogger(__name__)

COMPANIES_FILE = Path(__file__).with_name("companies.json")
BOARD_KEY = "data/board.json"
LOGO_PREFIX = "static/logos/"
BOARD_CACHE = "public, max-age=300"  # five minutes: a fresh sync shows up quickly
LOGO_CACHE = "public, max-age=604800"  # a week: logos rarely change
# 2: companies listed once; each listing names its company by id
FORMAT_VERSION = 2
LINK_ONLY = "link"


@dataclass
class Result:
    roles: int = 0
    skipped: int = 0  # roles outside the UK
    not_engineering: int = 0  # UK roles that are not engineering
    kept: list[str] = field(default_factory=list)  # companies whose site failed; previous roles kept
    new_logos: list[str] = field(default_factory=list)
    missing_logos: list[str] = field(default_factory=list)


def load_companies(path: Path = COMPANIES_FILE) -> list[dict]:
    companies = json.loads(path.read_text())
    names = [c["name"] for c in companies]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate company name in companies.json")
    for company in companies:
        # "link" companies publish no feed we may use; the board links to their careers site
        needed = ("name", "industry", "ats", "website") + (
            ("careers_url",) if company.get("ats") == LINK_ONLY else ("board",)
        )
        missing = [key for key in needed if not company.get(key)]
        if missing:
            raise ValueError(f"{company.get('name', '?')} is missing {', '.join(missing)}")
        if company.get("careers_url") and not company["careers_url"].startswith("https://"):
            raise ValueError(f"{company['name']} careers_url must be https")
    return companies


def role_id(source_id: str) -> str:
    """Stable across syncs, so a saved role still points at the same listing tomorrow."""
    return hashlib.sha256(source_id.encode()).hexdigest()[:16]


def company_entry(company: dict, rank: int, logo: str | None) -> dict:
    return {
        "id": slugify(company["name"]),
        "name": company["name"],
        "description": company.get("description", ""),
        "industry": company["industry"],
        "location": company.get("location", ""),
        "size": "",
        "rank": rank,
        "is_top": True,
        "is_verified": False,
        "profile_url": None,
        "logo": logo,
        "stage": company.get("stage", ""),
        "founded": None,
        "funding": "",
        "mission": "",
        "investors": "",
        "perks": "",
        "website": company["website"],
        # set for companies whose roles are only listed on their own site
        "careers_url": company.get("careers_url", ""),
    }


def listing_entry(role: Role, company_id: str, today: str) -> dict:
    return {
        "id": role_id(role.source_id),
        "job_title": role.title[:255],
        "description": role.description,
        "category": classify.work_type(role.title, role.department),
        "seniority": classify.seniority(role.title),
        "salary": role.salary,
        "region": role.location[:255],
        "arrangement": classify.arrangement(role),
        "premium": False,
        "application_url": role.apply_url or role.url,
        "posted_at": role.posted_at.isoformat() if role.posted_at else None,
        # it is listed on the employer's own site right now, so it is open
        "verified_at": today,
        "company": company_id,
    }


def _fetch(company: dict) -> tuple[dict, list[Role] | None]:
    if company["ats"] == LINK_ONLY:
        return company, []
    try:
        return company, fetch(company["ats"], company["board"])
    except SourceError as error:
        log.warning("Could not read %s: %s", company["name"], error)
        return company, None


def ensure_logos(store: Store, companies: list[dict], result: Result) -> dict[str, str]:
    """company slug -> logo path on the site. Fetches any logo not already stored."""
    stored = {}
    for key in store.keys(LOGO_PREFIX):
        stem = key[len(LOGO_PREFIX) :].rsplit(".", 1)[0]
        stored[stem] = "/" + key
    for company in companies:
        stem = slugify(company["name"])
        if stem in stored:
            continue
        found = find_logo(company["website"])
        if not found:
            result.missing_logos.append(company["name"])
            continue
        body, extension, _ = found
        key = f"{LOGO_PREFIX}{stem}.{extension}"
        store.write(key, body, CONTENT_TYPES[extension], LOGO_CACHE)
        stored[stem] = "/" + key
        result.new_logos.append(company["name"])
    return stored


def build(store: Store, companies: list[dict] | None = None, now: datetime | None = None, workers: int = 8) -> Result:
    companies = companies if companies is not None else load_companies()
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    result = Result()

    previous = json.loads(store.read(BOARD_KEY) or b"{}")
    previous_by_company: dict[str, list[dict]] = {}
    if previous.get("version") == FORMAT_VERSION:
        for listing in previous.get("listings", []):
            previous_by_company.setdefault(listing["company"], []).append(listing)

    logos = ensure_logos(store, companies, result)

    rank_by_industry: dict[str, int] = {}
    entries = {}
    for company in companies:
        rank = rank_by_industry[company["industry"]] = rank_by_industry.get(company["industry"], 0) + 1
        stem = slugify(company["name"])
        entries[company["name"]] = company_entry(company, rank, logos.get(stem))

    listings: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for company, roles in pool.map(_fetch, companies):
            entry = entries[company["name"]]
            if roles is None:
                listings += previous_by_company.get(entry["id"], [])
                result.kept.append(company["name"])
                continue
            for role in roles:
                if not role.title or not (role.apply_url or role.url):
                    continue
                if not classify.is_uk(role):
                    result.skipped += 1
                    continue
                if not classify.is_engineering(role.title):
                    result.not_engineering += 1
                    continue
                listings.append(listing_entry(role, entry["id"], today))

    # the same role can be listed twice by one company; keep one
    unique = list({listing["id"]: listing for listing in listings}.values())
    # newest first; roles without a posting date go last
    unique.sort(key=lambda row: row.get("posted_at") or "", reverse=True)
    result.roles = len(unique)
    previous_ids = {row["id"] for rows in previous_by_company.values() for row in rows}
    board = {
        "version": FORMAT_VERSION,
        "generated_at": now.isoformat(),
        "companies": list(entries.values()),
        "listings": unique,
        "added_ids": [row["id"] for row in unique if row["id"] not in previous_ids],
    }
    store.write(
        BOARD_KEY,
        json.dumps(board, ensure_ascii=False, separators=(",", ":")).encode(),
        "application/json",
        BOARD_CACHE,
    )
    return result

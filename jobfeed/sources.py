"""Read open roles from companies' public careers-site APIs.

Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee and Personio each publish a company's open roles as JSON for exactly this
purpose: embedding them on other sites. Each fetcher turns one company's board into a
list of `Role`s in a common shape. Nothing here touches a database.
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

USER_AGENT = "orbbits-job-sync/0.1"
TIMEOUT = 30
DESCRIPTION_LIMIT = 500


class SourceError(Exception):
    """The careers site could not be read. Existing roles should be left untouched."""


@dataclass(frozen=True)
class Role:
    source_id: str
    title: str
    location: str
    department: str
    url: str
    apply_url: str
    posted_at: datetime | None
    # "remote", "hybrid", "onsite" or "" when the site does not say
    workplace: str
    # ISO country name or code when the site gives one
    country: str
    salary: str
    description: str


PAGE_DELAY = 1.0  # seconds between pages from the same site
MAX_PAGES = 40  # never walk more than this many pages of one site


def _request(url: str, body: dict | None = None, accept: str = "application/json") -> bytes:
    if not url.startswith("https://"):
        raise SourceError(f"Refusing non-https URL: {url}")
    headers = {"Accept": accept, "User-Agent": USER_AGENT}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    for attempt in (1, 2):
        request = urllib.request.Request(url, data=data, headers=headers)  # noqa: S310 - scheme checked above
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
                return response.read()
        except urllib.error.HTTPError as error:
            # the site asked us to slow down: wait once, then give up for today
            if error.code == 429 and attempt == 1:
                time.sleep(int(error.headers.get("Retry-After") or 0) or 30)
                continue
            raise SourceError(f"{url}: {error}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise SourceError(f"{url}: {error}") from error
    raise SourceError(f"{url}: still rate limited")


def get_json(url: str, body: dict | None = None):
    try:
        return json.loads(_request(url, body))
    except ValueError as error:
        raise SourceError(f"{url}: not JSON") from error


def get_text(url: str) -> str:
    return _request(url, accept="text/html").decode("utf-8", "replace")


def plain_text(markup: str) -> str:
    """Readable text from a job description, in full (the board shortens it with `shorten`)."""
    text = html.unescape(markup or "")
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def shorten(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    """The description cut at a sentence where possible."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = cut.rfind(". ")
    return cut[: end + 1] if end > limit // 2 else cut.rsplit(" ", 1)[0] + "…"


def parse_time(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):  # Lever: epoch milliseconds
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def safe_url(value: str | None) -> str:
    return value if value and value.startswith(("https://", "http://")) else ""


CURRENCY_SYMBOLS = {"GBP": "£", "EUR": "€", "USD": "$"}


def salary_text(low, high, currency: str | None, interval: str = "") -> str:
    """'£80k – £100k' for annual pounds-sterling salaries; empty for anything else.

    Roles listed in several countries often publish only their US range, which would
    mislead someone applying from the UK, so other currencies are dropped.
    """
    if not currency or currency.upper() != "GBP" or interval and "year" not in interval.lower():
        return ""
    symbol = CURRENCY_SYMBOLS["GBP"]
    values = [v for v in (low, high) if v]
    if not values:
        return ""
    parts = [f"{symbol}{round(float(v) / 1000):g}k" for v in values]
    return " – ".join(dict.fromkeys(parts))


def workplace_from_text(text: str) -> str:
    lowered = text.lower()
    if "hybrid" in lowered:
        return "hybrid"
    if "remote" in lowered:
        return "remote"
    return ""


def fetch_greenhouse(board: str) -> list[Role]:
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    roles = []
    for job in data.get("jobs") or []:
        location = (job.get("location") or {}).get("name") or ""
        roles.append(
            Role(
                source_id=f"greenhouse:{board}:{job['id']}",
                title=(job.get("title") or "").strip(),
                location=location,
                department=", ".join(d["name"] for d in job.get("departments") or [] if d.get("name")),
                url=safe_url(job.get("absolute_url")),
                apply_url=safe_url(job.get("absolute_url")),
                posted_at=parse_time(job.get("first_published") or job.get("updated_at")),
                workplace=workplace_from_text(location),
                country="",
                salary="",
                description=plain_text(job.get("content") or ""),
            )
        )
    return roles


LEVER_WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}


def fetch_lever(board: str) -> list[Role]:
    data = get_json(f"https://api.lever.co/v0/postings/{board}?mode=json")
    if not isinstance(data, list):
        raise SourceError(f"Unexpected Lever response for {board}")
    roles = []
    for job in data:
        categories = job.get("categories") or {}
        locations = categories.get("allLocations") or [categories.get("location") or ""]
        location = "; ".join(dict.fromkeys(filter(None, locations)))
        pay = job.get("salaryRange") or {}
        roles.append(
            Role(
                source_id=f"lever:{board}:{job['id']}",
                title=(job.get("text") or "").strip(),
                location=location,
                department=categories.get("department") or categories.get("team") or "",
                url=safe_url(job.get("hostedUrl")),
                apply_url=safe_url(job.get("applyUrl") or job.get("hostedUrl")),
                posted_at=parse_time(job.get("createdAt")),
                workplace=LEVER_WORKPLACE.get((job.get("workplaceType") or "").lower(), "")
                or workplace_from_text(location),
                country=job.get("country") or "",
                salary=salary_text(pay.get("min"), pay.get("max"), pay.get("currency"), pay.get("interval") or ""),
                description=plain_text(job.get("descriptionPlain") or job.get("description") or ""),
            )
        )
    return roles


ASHBY_WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}


def fetch_ashby(board: str) -> list[Role]:
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true")
    roles = []
    for job in data.get("jobs") or []:
        if job.get("isListed") is False:
            continue
        locations = [job.get("location") or ""]
        locations += [s.get("location") or "" for s in job.get("secondaryLocations") or []]
        location = "; ".join(dict.fromkeys(filter(None, locations)))
        country = ((job.get("address") or {}).get("postalAddress") or {}).get("addressCountry") or ""
        salary = ""
        for tier in (job.get("compensation") or {}).get("compensationTiers") or []:
            for part in tier.get("components") or []:
                if part.get("compensationType") == "Salary":
                    salary = salary_text(
                        part.get("minValue"), part.get("maxValue"), part.get("currencyCode"), part.get("interval") or ""
                    )
                    break
            if salary:
                break
        workplace = ASHBY_WORKPLACE.get((job.get("workplaceType") or "").lower(), "")
        if not workplace and job.get("isRemote"):
            workplace = "remote"
        roles.append(
            Role(
                source_id=f"ashby:{board}:{job['id']}",
                title=(job.get("title") or "").strip(),
                location=location,
                department=job.get("department") or job.get("team") or "",
                url=safe_url(job.get("jobUrl")),
                apply_url=safe_url(job.get("applyUrl") or job.get("jobUrl")),
                posted_at=parse_time(job.get("publishedAt")),
                workplace=workplace or workplace_from_text(location),
                country=country,
                salary=salary,
                description=plain_text(job.get("descriptionPlain") or job.get("descriptionHtml") or ""),
            )
        )
    return roles


# --- Big tech careers sites ---------------------------------------------------------------
# Each reads only what the company's own careers site publishes for its search page, at a
# polite pace, and only where the site's robots.txt does not disallow it.


def fetch_amazon(country: str) -> list[Role]:
    """amazon.jobs search feed, for one country (ISO 3166 alpha-3, e.g. GBR)."""
    roles: list[Role] = []
    for page in range(MAX_PAGES):
        data = get_json(
            "https://www.amazon.jobs/en/search.json"
            f"?normalized_country_code%5B%5D={country}&result_limit=100&offset={page * 100}&sort=recent"
        )
        jobs = data.get("jobs") or []
        for job in jobs:
            path = job.get("job_path") or ""
            url = f"https://www.amazon.jobs{path}" if path.startswith("/") else ""
            posted = None
            try:
                posted = datetime.strptime(job.get("posted_date") or "", "%B %d, %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
            roles.append(
                Role(
                    source_id=f"amazon:{country}:{job.get('id_icims') or job.get('id')}",
                    title=(job.get("title") or "").strip(),
                    location=job.get("normalized_location") or job.get("location") or "",
                    department=job.get("job_category") or "",
                    url=url,
                    apply_url=url,
                    posted_at=posted,
                    workplace="",
                    country=country,
                    salary="",
                    description=plain_text(job.get("description_short") or job.get("description") or ""),
                )
            )
        if len(jobs) < 100 or len(roles) >= int(data.get("hits") or 0):
            break
        time.sleep(PAGE_DELAY)
    return roles


def _workday_posted(text: str, now: datetime) -> datetime | None:
    """Workday only says "Posted Today", "Posted Yesterday", "Posted 3 Days Ago" or "30+"."""
    lowered = (text or "").lower()
    if "today" in lowered:
        return now
    if "yesterday" in lowered:
        return now - timedelta(days=1)
    found = re.search(r"(\d+)\+?\s*days?", lowered)
    return now - timedelta(days=int(found.group(1))) if found else None


def fetch_workday(board: str) -> list[Role]:
    """A company's public Workday careers site. board = "<host>:<tenant>:<site>",
    e.g. "nvidia.wd5:nvidia:NVIDIAExternalCareerSite". UK roles only."""
    host, tenant, site = board.split(":")
    api = f"https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    public = f"https://{host}.myworkdayjobs.com/en-US/{site}"
    first = get_json(api, {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})

    def facets(items):
        # location filters can be nested one level down, inside a group
        for item in items or []:
            if item.get("facetParameter") and item.get("values") and "id" not in item:
                yield item
                yield from facets(item["values"])

    # sites name the filter differently: "locationCountry", "Country_and_Jurisdiction", "locations"…
    # country filters first, as a location filter may list one UK city rather than the country
    candidates = sorted(
        (
            (0 if "country" in facet["facetParameter"].lower() else 1, facet["facetParameter"], value["id"])
            for facet in facets(first.get("facets"))
            if "country" in facet["facetParameter"].lower() or facet["facetParameter"].lower().startswith("location")
            for value in facet["values"]
            if (value.get("descriptor") or "").strip().lower() in ("united kingdom", "uk", "great britain")
        ),
        key=lambda c: c[0],
    )
    country = (candidates[0][1], candidates[0][2]) if candidates else None
    if country is None:
        return []
    facet, uk_id = country
    uk = [uk_id]
    time.sleep(PAGE_DELAY)
    now = datetime.now(timezone.utc)
    roles: list[Role] = []
    for page in range(MAX_PAGES):
        data = get_json(api, {"appliedFacets": {facet: uk}, "limit": 20, "offset": page * 20, "searchText": ""})
        postings = data.get("jobPostings") or []
        for job in postings:
            path = job.get("externalPath") or ""
            # "/job/UK-Bristol/Senior-Engineer_JR123" -> "Bristol, UK"
            place = path.split("/")[2] if path.count("/") >= 3 else ""
            location = job.get("locationsText") or ""
            if not location or re.fullmatch(r"\d+ Locations", location):
                country_code, _, city = place.partition("-")
                location = f"{city.replace('-', ' ')}, {country_code}" if city else place
            roles.append(
                Role(
                    source_id=f"workday:{tenant}:{(job.get('bulletFields') or [path])[0]}",
                    title=(job.get("title") or "").strip(),
                    location=location,
                    department="",
                    url=public + path if path.startswith("/") else "",
                    apply_url=public + path if path.startswith("/") else "",
                    posted_at=_workday_posted(job.get("postedOn") or "", now),
                    workplace=workplace_from_text(location),
                    country="GB",
                    salary="",
                    description="",
                )
            )
        if len(postings) < 20 or len(roles) >= int(data.get("total") or 0):
            break
        time.sleep(PAGE_DELAY)
    return roles


APPLE_STATE = re.compile(r'__staticRouterHydrationData\s*=\s*JSON\.parse\(("(?:[^"\\]|\\.)*")\)')


def fetch_apple(location: str) -> list[Role]:
    """jobs.apple.com search results for one location, e.g. "united-kingdom-GBR".

    The search page carries its results as JSON for the browser to render; that is read here
    instead of the visible HTML.
    """
    roles: list[Role] = []
    total = None
    for page in range(1, MAX_PAGES + 1):
        # a fixed order, so pages do not overlap
        markup = get_text(f"https://jobs.apple.com/en-gb/search?location={location}&sort=newest&page={page}")
        found = APPLE_STATE.search(markup)
        if not found:
            raise SourceError("Apple's search page has changed shape")
        try:
            state = json.loads(json.loads(found.group(1)))["loaderData"]["search"]
        except (ValueError, KeyError, TypeError) as error:
            raise SourceError("Apple's search data has changed shape") from error
        results = state.get("searchResults") or []
        total = int(state.get("totalRecords") or 0) if total is None else total
        for job in results:
            places = job.get("locations") or []
            location_text = "; ".join(
                dict.fromkeys(
                    ", ".join(dict.fromkeys(filter(None, [place.get("city") or place.get("name"), place.get("countryName")])))
                    for place in places
                )
            )
            url = (
                f"https://jobs.apple.com/en-gb/details/{job.get('positionId')}/{job.get('transformedPostingTitle', '')}"
            )
            roles.append(
                Role(
                    source_id=f"apple:{job.get('positionId')}",
                    title=(job.get("postingTitle") or "").strip(),
                    location=location_text,
                    department=(job.get("team") or {}).get("teamName") or "",
                    url=url,
                    apply_url=url,
                    posted_at=parse_time(job.get("postDateInGMT")),
                    workplace="remote" if job.get("homeOffice") else "",
                    country=(places[0].get("countryName") if places else "") or "",
                    salary="",
                    description=plain_text(job.get("jobSummary") or ""),
                )
            )
        if not results or len(roles) >= total:
            break
        time.sleep(PAGE_DELAY)
    return list({role.source_id: role for role in roles}.values())



# --- More careers systems -------------------------------------------------------------------
# Like Greenhouse, Lever and Ashby, each publishes a company's open roles as JSON or XML for
# embedding on other sites. No keys needed.


def fetch_workable(board: str) -> list[Role]:
    """Workable's public job widget feed (apply.workable.com/<board>)."""
    data = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{board}?details=true")
    roles = []
    for job in data.get("jobs") or []:
        places = [job] + list(job.get("locations") or [])
        names = []
        country = job.get("country") or ""
        for place in places:
            if place.get("hidden"):
                continue
            names.append(", ".join(filter(None, [place.get("city"), place.get("country")])))
            if (place.get("countryCode") or "").upper() == "GB":
                country = "United Kingdom"
        location = "; ".join(dict.fromkeys(filter(None, names)))
        remote = str(job.get("telecommuting")).lower() == "true"
        roles.append(
            Role(
                source_id=f"workable:{board}:{job.get('shortcode')}",
                title=(job.get("title") or "").strip(),
                location=location + ("; Remote" if remote and "remote" not in location.lower() else ""),
                department=job.get("department") or job.get("function") or "",
                url=safe_url(job.get("url") or job.get("shortlink")),
                apply_url=safe_url(job.get("application_url") or job.get("url")),
                posted_at=parse_time(job.get("published_on") or job.get("created_at")),
                workplace="remote" if remote else workplace_from_text(location),
                country=country,
                salary="",
                description=plain_text(job.get("description") or ""),
            )
        )
    return roles


SMARTRECRUITERS_DETAILS = 120  # most UK roles to fetch descriptions for, one request each


def fetch_smartrecruiters(board: str) -> list[Role]:
    """SmartRecruiters' public Posting API. Large employers list thousands of roles worldwide,
    so only UK postings are read, then their descriptions one by one."""
    base = f"https://api.smartrecruiters.com/v1/companies/{board}/postings"
    postings, offset = [], 0
    for _ in range(MAX_PAGES):
        page = get_json(f"{base}?limit=100&offset={offset}&country=gb")
        content = page.get("content") or []
        postings += content
        offset += len(content)
        if not content or offset >= (page.get("totalFound") or 0):
            break
        time.sleep(PAGE_DELAY)
    roles = []
    for index, job in enumerate(postings):
        place = job.get("location") or {}
        description, url = "", ""
        if index < SMARTRECRUITERS_DETAILS:
            try:
                detail = get_json(f"{base}/{job['id']}")
                sections = (detail.get("jobAd") or {}).get("sections") or {}
                description = plain_text(
                    " ".join((sections.get(k) or {}).get("text") or "" for k in ("jobDescription", "qualifications"))
                )
                url = safe_url(detail.get("postingUrl"))
            except SourceError:
                pass
            time.sleep(0.2)
        url = url or f"https://jobs.smartrecruiters.com/{board}/{job['id']}"
        workplace = "remote" if place.get("remote") else "hybrid" if place.get("hybrid") else ""
        roles.append(
            Role(
                source_id=f"smartrecruiters:{board}:{job['id']}",
                title=(job.get("name") or "").strip(),
                location=re.sub(r"(,\s*)+", ", ", place.get("fullLocation") or "").strip(", ")
                or ", ".join(filter(None, [place.get("city"), "United Kingdom"])),
                department=(job.get("department") or {}).get("label") or (job.get("function") or {}).get("label") or "",
                url=url,
                apply_url=url,
                posted_at=parse_time(job.get("releasedDate")),
                workplace=workplace,
                country="United Kingdom" if (place.get("country") or "").lower() == "gb" else place.get("country") or "",
                salary="",
                description=description,
            )
        )
    return roles


def fetch_recruitee(board: str) -> list[Role]:
    """Recruitee's public offers feed (<board>.recruitee.com)."""
    data = get_json(f"https://{board}.recruitee.com/api/offers/")
    roles = []
    for job in data.get("offers") or []:
        places = job.get("locations") or [job]
        location = "; ".join(
            dict.fromkeys(filter(None, (", ".join(filter(None, [p.get("city"), p.get("country")])) for p in places)))
        )
        uk = any((p.get("country_code") or "").upper() == "GB" for p in places)
        pay = job.get("salary") or {}
        workplace = "remote" if job.get("remote") else "hybrid" if job.get("hybrid") else "onsite" if job.get("on_site") else ""
        roles.append(
            Role(
                source_id=f"recruitee:{board}:{job.get('id')}",
                title=(job.get("title") or "").strip(),
                location=location,
                department=job.get("department") or "",
                url=safe_url(job.get("careers_url")),
                apply_url=safe_url(job.get("careers_apply_url") or job.get("careers_url")),
                posted_at=parse_time((job.get("published_at") or job.get("created_at") or "").replace(" UTC", "+00:00")),
                workplace=workplace,
                country="United Kingdom" if uk else job.get("country") or "",
                salary=salary_text(pay.get("min"), pay.get("max"), pay.get("currency"), "year" if pay.get("period") == "year" else pay.get("period") or ""),
                description=plain_text((job.get("description") or "") + " " + (job.get("requirements") or "")),
            )
        )
    return roles


def fetch_personio(board: str) -> list[Role]:
    """Personio's public XML job feed (<board>.jobs.personio.de, or .com)."""
    import xml.etree.ElementTree as ElementTree

    domain = "com" if board.endswith(".com") else "de"
    name = board.removesuffix(".com")
    raw = _request(f"https://{name}.jobs.personio.{domain}/xml?language=en", accept="application/xml")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as error:
        raise SourceError(f"Personio {board}: not XML") from error
    roles = []
    for job in root.findall("position"):
        text = lambda tag: (job.findtext(tag) or "").strip()  # noqa: E731
        offices = [text("office")] + [(o.text or "").strip() for o in job.findall("additionalOffices/office")]
        location = "; ".join(dict.fromkeys(filter(None, offices)))
        description = " ".join(
            (d.findtext("value") or "") for d in job.findall("jobDescriptions/jobDescription")
        )
        job_id = text("id")
        url = f"https://{name}.jobs.personio.{domain}/job/{job_id}?language=en"
        roles.append(
            Role(
                source_id=f"personio:{name}:{job_id}",
                title=text("name"),
                location=location,
                department=text("department"),
                url=url,
                apply_url=url,
                posted_at=parse_time(text("createdAt")),
                workplace=workplace_from_text(location),
                country="",
                salary="",
                description=plain_text(description),
            )
        )
    return roles


ORACLE_PAGE = 25


def fetch_oracle(board: str) -> list[Role]:
    """Oracle Recruiting Cloud careers sites (e.g. JPMorgan Chase). board = "<host>:<site>",
    e.g. "jpmc.fa.oraclecloud.com:CX_1001". UK roles only."""
    host, site = board.split(":")
    api = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"

    def search(extra: str):
        finder = f"findReqs;siteNumber={site},{extra}"
        data = get_json(f"{api}?onlyData=true&expand=requisitionList.secondaryLocations&finder={finder}")
        return (data.get("items") or [{}])[0]

    first = search("facetsList=LOCATIONS,limit=1")
    uk = next(
        (loc.get("Id") for loc in first.get("locationsFacet") or [] if (loc.get("Name") or "").strip().lower() == "united kingdom"),
        None,
    )
    if uk is None:
        return []
    roles: list[Role] = []
    for page in range(MAX_PAGES):
        time.sleep(PAGE_DELAY)
        result = search(f"locationId={uk},limit={ORACLE_PAGE},offset={page * ORACLE_PAGE},sortBy=POSTING_DATES_DESC")
        jobs = result.get("requisitionList") or []
        for job in jobs:
            places = [job.get("PrimaryLocation") or ""] + [
                p.get("Name") or "" for p in job.get("secondaryLocations") or []
            ]
            location = "; ".join(dict.fromkeys(filter(None, places)))
            url = f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{job.get('Id')}"
            roles.append(
                Role(
                    source_id=f"oracle:{host}:{job.get('Id')}",
                    title=(job.get("Title") or "").strip(),
                    location=location,
                    department=job.get("JobFamily") or job.get("Department") or "",
                    url=url,
                    apply_url=url,
                    posted_at=parse_time(job.get("PostedDate")),
                    workplace=workplace_from_text(job.get("WorkplaceType") or "") or workplace_from_text(location),
                    country="United Kingdom" if (job.get("PrimaryLocationCountry") or "").upper() == "GB" else "",
                    salary="",
                    description=plain_text(
                        (job.get("ShortDescriptionStr") or "") + " " + (job.get("ExternalResponsibilitiesStr") or "")
                    ),
                )
            )
        if len(jobs) < ORACLE_PAGE:
            break
    return roles

FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "amazon": fetch_amazon,
    "workday": fetch_workday,
    "apple": fetch_apple,
    "workable": fetch_workable,
    "smartrecruiters": fetch_smartrecruiters,
    "recruitee": fetch_recruitee,
    "personio": fetch_personio,
    "oracle": fetch_oracle,
}


def fetch(ats: str, board: str) -> list[Role]:
    try:
        fetcher = FETCHERS[ats]
    except KeyError:
        raise SourceError(f"Unknown careers system: {ats}") from None
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", board):
        raise SourceError(f"Invalid board name: {board!r}")
    return fetcher(board)

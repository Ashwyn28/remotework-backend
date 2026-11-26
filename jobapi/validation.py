"""Check data the browser sends before it is stored. Anything unexpected is dropped or refused."""
import re

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# role ids from the sync are 16 hex characters; older numeric ids also fit
JOB_ID = re.compile(r"^[0-9a-f]{1,16}$")
PLACES = {"london", "uk", "remote"}
SENIORITIES = {"junior", "mid", "senior", "staff", "manager"}
STAGES = {"seed", "series-a", "series-b", "series-c-plus", "bootstrapped", "public"}
STATUSES = {"saved", "applied"}
MAX_LIST = 30
MAX_TRACKED = 2000


class Invalid(ValueError):
    pass


def _slugs(value, allowed=None):
    if not isinstance(value, list) or len(value) > MAX_LIST:
        raise Invalid("expected a short list")
    out = []
    for item in value:
        if not isinstance(item, str) or len(item) > 64 or not SLUG.match(item):
            raise Invalid("invalid value in list")
        if allowed is not None and item not in allowed:
            raise Invalid(f"unknown value: {item}")
        if item not in out:
            out.append(item)
    return out


def preferences(value) -> dict:
    if not isinstance(value, dict):
        raise Invalid("preferences must be an object")
    salary = value.get("minSalary", 0)
    if isinstance(salary, bool) or not isinstance(salary, int) or not 0 <= salary <= 1000:
        raise Invalid("minSalary must be a whole number of thousands")
    return {
        "industries": _slugs(value.get("industries", [])),
        "places": _slugs(value.get("places", []), PLACES),
        "workTypes": _slugs(value.get("workTypes", [])),
        "seniorities": _slugs(value.get("seniorities", []), SENIORITIES),
        "stages": _slugs(value.get("stages", []), STAGES),
        "minSalary": salary,
    }


def tracked(value) -> dict:
    if not isinstance(value, dict) or len(value) > MAX_TRACKED:
        raise Invalid("tracked must be an object of at most %d roles" % MAX_TRACKED)
    out = {}
    for job_id, entry in value.items():
        if not isinstance(job_id, str) or not JOB_ID.match(job_id):
            raise Invalid("invalid job id")
        if not isinstance(entry, dict) or entry.get("status") not in STATUSES:
            raise Invalid("invalid tracking status")
        at = entry.get("at")
        if isinstance(at, bool) or not isinstance(at, int) or at < 0:
            raise Invalid("invalid tracking time")
        out[job_id] = {"status": entry["status"], "at": at}
    return out

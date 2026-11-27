"""Pure rules that place an imported role on the board: where it is, what kind of work, how senior."""
from __future__ import annotations

import re

from .sources import Role

UK_PLACES = re.compile(
    r"\b(united kingdom|uk|u\.k\.|great britain|england|scotland|wales|northern ireland|london|"
    r"manchester|edinburgh|glasgow|bristol|cambridge|oxford|leeds|cardiff|belfast|birmingham|"
    r"newcastle|brighton|reading|sheffield|nottingham|liverpool)\b",
    re.I,
)
UK_COUNTRIES = {"united kingdom", "uk", "gb", "gbr", "great britain"}
# remote roles open to someone living in the UK
REMOTE_REGIONS = re.compile(r"\b(emea|europe|european|worldwide|global|anywhere)\b", re.I)


def is_uk(role: Role) -> bool:
    """True when someone based in the UK could do this role."""
    if role.country.strip().lower() in UK_COUNTRIES:
        return True
    if UK_PLACES.search(role.location):
        return True
    return role.workplace == "remote" and bool(REMOTE_REGIONS.search(role.location))


def arrangement(role: Role) -> str:
    """Display text the frontend reads as a work mode: 'Remote', 'Hybrid' or 'On-site'."""
    if role.workplace == "remote":
        return "Remote"
    if role.workplace == "hybrid":
        return "Hybrid"
    if role.workplace == "onsite":
        return "On-site"
    return ""


# Checked in order; the first rule that matches wins.
WORK_RULES = [
    ("design", re.compile(r"\b(designer|design lead|head of design|ux|ui/ux|user research)", re.I)),
    (
        "data",
        re.compile(
            r"\b(data|analytics|(product|bi|business intelligence|insights?|quantitative|quant) analyst|"
            r"machine learning|ml|ai engineer|research (scientist|engineer)|applied scientist|scientist|"
            r"statistician)\b",
            re.I,
        ),
    ),
    ("product", re.compile(r"\b(product (manager|owner|lead|director|operations)|head of product|vp,? product)", re.I)),
    (
        "sales",
        re.compile(
            r"\b(sales|account (executive|manager|director|partner)|business development|customer success|"
            r"partnerships?|go[- ]to[- ]market|gtm)\b",
            re.I,
        ),
    ),
    ("marketing", re.compile(r"\b(marketing|growth|brand|content|communications|social media|seo|events)\b", re.I)),
    (
        "engineering",
        re.compile(
            r"\b(engineer|engineering|developer|software|sre|devops|architect|infrastructure|"
            r"backend|frontend|full[- ]?stack|mobile|ios|android|qa|test)\b",
            re.I,
        ),
    ),
    # recognisably non-technical titles, so a team's department ("Engineering") cannot pull them in
    (
        "operations",
        re.compile(
            r"\b(procurement|finance|financial|accountant|accounting|payroll|tax|treasury|legal|counsel|"
            r"lawyer|paralegal|recruit\w*|talent|people|hr|workplace|office|facilities|executive assistant|"
            r"compliance|risk|grc|audit|operations|analyst|chief of staff)\b",
            re.I,
        ),
    ),
]


def work_type(title: str, department: str = "") -> str:
    for slug, pattern in WORK_RULES:
        if pattern.search(title):
            return slug
    for slug, pattern in WORK_RULES:
        if department and pattern.search(department):
            return slug
    return "operations"


# "Manager" in these titles names an individual role, not a people manager.
IC_MANAGER = re.compile(
    r"\b(product|account|program|programme|project|partner|partnerships|customer success|success|"
    r"marketing|community|campaign|content|relationship|territory|category|brand|events?) manager\b",
    re.I,
)
PEOPLE_MANAGER = re.compile(r"\bmanager\b", re.I)

SENIORITY_RULES = [
    ("junior", re.compile(r"\b(intern|internship|graduate|grad|apprentice|junior|entry[- ]level|associate engineer)\b", re.I)),
    (
        "manager",
        re.compile(
            r"\b(head of|director|vp|vice president|chief|cto|cfo|ceo|"
            r"(engineering|data|design|analytics|people|team|delivery) manager|manager,? (engineering|data))\b",
            re.I,
        ),
    ),
    ("staff", re.compile(r"\b(staff|principal|distinguished|lead|architect)\b", re.I)),
    ("manager", re.compile(r"\b(senior|general|regional|country) manager\b", re.I)),
    ("senior", re.compile(r"\b(senior|sr\.?|snr)\b", re.I)),
]


def seniority(title: str) -> str:
    for level, pattern in SENIORITY_RULES:
        if level == "senior" and PEOPLE_MANAGER.search(IC_MANAGER.sub("", title)):
            return "manager"  # "Senior Machine Learning Manager" manages people
        if pattern.search(title):
            return level
    if PEOPLE_MANAGER.search(IC_MANAGER.sub("", title)):
        return "manager"
    return "mid"


# --- Engineering focus ------------------------------------------------------------------------
# The board lists engineering roles only: software, data and ML engineering, infrastructure,
# security, hardware, QA and engineering leadership.

ENGINEERING_TITLE = re.compile(
    r"\b(engineer(ing)?s?|developer|programmer|sre|devops|devsecops|architect|swe|cto|"
    r"machine learning|ml ops|mlops|data scien\w*|research scientist|applied scientist|"
    r"security (analyst|researcher)|penetration tester|tech lead|technical lead)\b",
    re.I,
)
# engineering words in titles whose job is selling, supporting, hiring or administering
NOT_ENGINEERING = re.compile(
    r"\b(sales|pre-?sales|solutions?|customer|support|field|account|recruit\w*|talent|sourcer|"
    r"marketing|finance|legal|counsel|people|hr|payroll|executive assistant|assistant to|"
    r"coordinator|office|facilities|partnerships?|business development|community|content|"
    r"writer|enablement|evangelist|advocate|implementation|onboarding|professional services|"
    r"consultant|bid|commercial)\b",
    re.I,
)


def is_engineering(title: str) -> bool:
    """True for engineering roles; the board shows nothing else."""
    return bool(ENGINEERING_TITLE.search(title)) and not NOT_ENGINEERING.search(title)

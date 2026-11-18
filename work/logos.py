"""Company logos for the local Django tools, saved under work/static/logos/.

Finding the logo is shared with the sync Lambda (`jobfeed.logos`); this module only decides
where Django keeps it.
"""
import logging
from pathlib import Path

from jobfeed.logos import find_logo, slugify

log = logging.getLogger(__name__)

LOGO_DIR = Path(__file__).resolve().parent / "static" / "logos"


def logo_filename(company) -> str | None:
    """File name of the saved logo for a company, if there is one."""
    for path in LOGO_DIR.glob(f"{slugify(company.name)}.*"):
        return path.name
    return None


def ensure_logo(company, force: bool = False) -> str | None:
    """Make sure the company has a saved logo. Returns the source URL when one was fetched.

    Does nothing when a logo already exists (unless `force`) or the company has no website.
    Never raises: a missing logo falls back to the company's initials on the board.
    """
    if not company.website or (logo_filename(company) and not force):
        return None
    found = find_logo(company.website)
    if not found:
        log.warning("No usable logo found for %s (%s)", company.name, company.website)
        return None
    body, extension, url = found
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    stem = slugify(company.name)
    for old in LOGO_DIR.glob(f"{stem}.*"):
        old.unlink()
    (LOGO_DIR / f"{stem}.{extension}").write_bytes(body)
    return url

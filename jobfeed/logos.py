"""Find a company's logo on its own website. Pure functions; callers decide where to store it."""
import re
import unicodedata
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

USER_AGENT = "Mozilla/5.0 (compatible; orbbits-job-logo-fetch/0.1)"
MAX_BYTES = 512 * 1024
TIMEOUT = 20
EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
}
CONTENT_TYPES = {extension: kind for kind, extension in EXTENSIONS.items()}


def slugify(value: str) -> str:
    """The same slugs as Django's slugify: "incident.io" -> "incidentio", "Flo Health" -> "flo-health"."""
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-_")


class IconLinks(HTMLParser):
    """Collect <link rel="...icon..."> tags with their declared size."""

    def __init__(self):
        super().__init__()
        self.icons: list[tuple[int, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        attrs = dict(attrs)
        rel = (attrs.get("rel") or "").lower()
        href = attrs.get("href")
        if not href or "icon" not in rel or "mask-icon" in rel:
            return
        sizes = re.findall(r"(\d+)x\d+", attrs.get("sizes") or "")
        size = max(map(int, sizes)) if sizes else (180 if "apple-touch-icon" in rel else 32)
        if (attrs.get("type") or "").endswith("svg") or href.split("?")[0].endswith(".svg"):
            size = 512  # vector: sharp at any size
        self.icons.append((size, href))


def get(url: str) -> tuple[bytes, str]:
    if urlparse(url).scheme != "https":
        raise ValueError(f"not https: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("too large")
        return body, response.headers.get_content_type()


def candidates(website: str) -> list[str]:
    """Icon URLs to try, best first: declared icons by size, then the usual fixed paths."""
    found: list[tuple[int, str]] = []
    try:
        page, kind = get(website)
        if kind == "text/html":
            parser = IconLinks()
            parser.feed(page.decode("utf-8", "replace"))
            found = [(size, urljoin(website, href)) for size, href in parser.icons]
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        pass
    ordered = [url for _, url in sorted(found, key=lambda item: -item[0])]
    ordered += [urljoin(website, "/apple-touch-icon.png"), urljoin(website, "/favicon.ico")]
    host = urlparse(website).hostname or ""
    # last resort: a 128px icon from Google's favicon service, fetched once here, never by visitors
    ordered.append(f"https://www.google.com/s2/favicons?domain={host}&sz=128")
    return list(dict.fromkeys(url for url in ordered if url.startswith("https://")))


def find_logo(website: str) -> tuple[bytes, str, str] | None:
    """(image bytes, file extension, source URL) for the best icon a website offers, or None."""
    if not website:
        return None
    for url in candidates(website):
        try:
            body, kind = get(url)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            continue
        extension = EXTENSIONS.get(kind)
        if extension and len(body) >= 100:
            return body, extension, url
    return None

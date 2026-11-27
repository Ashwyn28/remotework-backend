import json
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from jobfeed import board, classify, sources
from jobfeed.storage import DirStore
from jobfeed.tests.test_board import COMPANIES, NOW, role


def replay(responses):
    """Patch get_json to answer by URL prefix, in order."""
    def fake(url, body=None):
        for prefix, payload in responses:
            if url.startswith(prefix):
                return payload
        raise AssertionError(f"unexpected request {url}")
    return mock.patch.object(sources, "get_json", side_effect=fake)


class WorkableTest(unittest.TestCase):
    def test_reads_uk_and_remote_roles(self):
        payload = {"jobs": [{
            "title": "Backend Engineer", "shortcode": "AB12", "telecommuting": True, "department": "Engineering",
            "url": "https://apply.workable.com/j/AB12", "application_url": "https://apply.workable.com/j/AB12/apply",
            "published_on": "2026-11-20", "country": "United Kingdom", "city": "London",
            "locations": [{"country": "United Kingdom", "countryCode": "GB", "city": "London", "hidden": False}],
            "description": "<p>Build APIs.</p>",
        }]}
        with replay([("https://apply.workable.com/", payload)]):
            [r] = sources.fetch("workable", "acme")
        self.assertEqual((r.title, r.workplace, r.country), ("Backend Engineer", "remote", "United Kingdom"))
        self.assertIn("London", r.location)
        self.assertEqual(r.description, "Build APIs.")
        self.assertTrue(classify.is_uk(r))


class SmartRecruitersTest(unittest.TestCase):
    def test_reads_uk_postings_with_descriptions(self):
        listing = {"totalFound": 1, "content": [{
            "id": "77", "name": "Platform Engineer", "releasedDate": "2026-11-25T10:00:00.000Z",
            "location": {"city": "London", "country": "gb", "remote": False, "hybrid": True, "fullLocation": "London, , United Kingdom"},
            "department": {"label": "Technology"},
        }]}
        detail = {"postingUrl": "https://jobs.smartrecruiters.com/Acme/77-platform-engineer",
                  "jobAd": {"sections": {"jobDescription": {"text": "<p>Run Kubernetes.</p>"}, "qualifications": {"text": ""}}}}
        with replay([("https://api.smartrecruiters.com/v1/companies/Acme/postings?", listing),
                     ("https://api.smartrecruiters.com/v1/companies/Acme/postings/77", detail)]), \
                mock.patch.object(sources.time, "sleep"):
            [r] = sources.fetch("smartrecruiters", "Acme")
        self.assertEqual((r.location, r.workplace, r.country), ("London, United Kingdom", "hybrid", "United Kingdom"))
        self.assertEqual(r.url, "https://jobs.smartrecruiters.com/Acme/77-platform-engineer")
        self.assertEqual(r.description, "Run Kubernetes.")


class RecruiteeTest(unittest.TestCase):
    def test_reads_offers(self):
        payload = {"offers": [{
            "id": 5, "title": "Frontend Developer", "careers_url": "https://acme.recruitee.com/o/fe",
            "careers_apply_url": "https://acme.recruitee.com/o/fe/c/new", "published_at": "2026-11-24 10:10:44 UTC",
            "department": "Tech", "hybrid": True, "remote": False, "on_site": False,
            "locations": [{"city": "Manchester", "country": "United Kingdom", "country_code": "GB"}],
            "description": "<p>React.</p>", "requirements": "",
            "salary": {"min": 70000, "max": 90000, "currency": "GBP", "period": "year"},
        }]}
        with replay([("https://acme.recruitee.com/api/offers/", payload)]):
            [r] = sources.fetch("recruitee", "acme")
        self.assertEqual((r.workplace, r.country, r.salary), ("hybrid", "United Kingdom", "£70k – £90k"))
        self.assertEqual(r.posted_at, datetime(2026, 11, 24, 10, 10, 44, tzinfo=timezone.utc))


class PersonioTest(unittest.TestCase):
    def test_reads_xml_feed(self):
        xml = b"""<?xml version="1.0"?><workzag-jobs><position><id>42</id><office>London</office>
        <additionalOffices><office>Berlin</office></additionalOffices><department>Engineering</department>
        <name>Senior Python Engineer</name><jobDescriptions><jobDescription><name>About</name>
        <value>&lt;p&gt;Python and Postgres.&lt;/p&gt;</value></jobDescription></jobDescriptions>
        <createdAt>2026-11-26T16:55:38+00:00</createdAt></position></workzag-jobs>"""
        with mock.patch.object(sources, "_request", return_value=xml):
            [r] = sources.fetch("personio", "acme")
        self.assertEqual((r.title, r.location), ("Senior Python Engineer", "London; Berlin"))
        self.assertEqual(r.url, "https://acme.jobs.personio.de/job/42?language=en")
        self.assertEqual(r.description, "Python and Postgres.")


class OracleTest(unittest.TestCase):
    def test_reads_uk_requisitions(self):
        facets = {"items": [{"locationsFacet": [{"Name": "United States", "Id": 1}, {"Name": "United Kingdom", "Id": 99}]}]}
        page = {"items": [{"requisitionList": [{
            "Id": "210", "Title": "Software Engineer III", "PrimaryLocation": "LONDON, United Kingdom",
            "PrimaryLocationCountry": "GB", "PostedDate": "2026-11-27", "WorkplaceType": "Hybrid",
            "ShortDescriptionStr": "Build trading systems.", "JobFamily": "Technology",
        }]}]}
        calls = []

        def fake(url, body=None):
            calls.append(url)
            return facets if "facetsList" in url else page
        with mock.patch.object(sources, "get_json", side_effect=fake), mock.patch.object(sources.time, "sleep"):
            [r] = sources.fetch("oracle", "acme.fa.oraclecloud.com:CX_1")
        self.assertIn("locationId=99", calls[1])
        self.assertEqual((r.workplace, r.country), ("hybrid", "United Kingdom"))
        self.assertEqual(r.url, "https://acme.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/210")


class WorkdayCountryFacetTest(unittest.TestCase):
    def test_finds_country_filter_by_any_name(self):
        first = {"facets": [{"facetParameter": "Country_and_Jurisdiction", "values": [
            {"descriptor": "United Kingdom", "id": "gb-id"}, {"descriptor": "India", "id": "in-id"}]}]}
        page = {"jobPostings": [{"title": "Data Engineer", "externalPath": "/job/London/Data-Engineer_R1",
                                 "locationsText": "London", "postedOn": "Posted Today"}]}
        bodies = []

        def fake(url, body=None):
            bodies.append(body)
            return first if body and body.get("limit") == 1 else page if len(bodies) == 2 else {"jobPostings": []}
        with mock.patch.object(sources, "get_json", side_effect=fake), mock.patch.object(sources.time, "sleep"):
            roles = sources.fetch("workday", "acme.wd3:acme:Careers")
        self.assertEqual(bodies[1]["appliedFacets"], {"Country_and_Jurisdiction": ["gb-id"]})
        self.assertEqual(roles[0].title, "Data Engineer")


class EngineeringOnlyTest(unittest.TestCase):
    def test_titles(self):
        yes = ["Senior Software Engineer", "Engineering Manager", "Data Engineer", "Research Scientist", "SRE", "iOS Developer",
               "Tech Lead - Autonomy Performance", "Head of Data Science", "Senior Penetration Tester", "Staff Product Engineer"]
        no = ["Sales Engineer", "Solutions Engineer", "Technical Recruiter - Engineering", "Product Manager", "Account Executive",
              "Principal Business Developer - ISV, GenAI GTM Specialists", "Engineering Project Manager",
              "Data Science Product Manager", "Technical Program Manager", "UK - Specialist: Seasonal, Part-time"]
        for title in yes:
            self.assertTrue(classify.is_engineering(title), title)
        for title in no:
            self.assertFalse(classify.is_engineering(title), title)

    def test_board_keeps_engineering_newest_first(self):
        store = DirStore(tempfile.mkdtemp())
        for stem in ("acme-bank", "robo-co"):
            store.write(f"static/logos/{stem}.png", b"png", "image/png", "")
        roles = {
            "acme": [
                role("greenhouse:acme:1", title="Backend Engineer", posted_at=datetime(2026, 11, 1, tzinfo=timezone.utc)),
                role("greenhouse:acme:2", title="Account Executive"),
                role("greenhouse:acme:3", title="Staff Engineer", posted_at=datetime(2026, 11, 14, tzinfo=timezone.utc)),
            ],
            "robo": [],
        }
        with mock.patch.object(board, "fetch", side_effect=lambda ats, name: roles[name]):
            result = board.build(store, COMPANIES, now=NOW, workers=2)
        listings = json.loads(store.read(board.BOARD_KEY))["listings"]
        self.assertEqual([l["job_title"] for l in listings], ["Staff Engineer", "Backend Engineer"])
        self.assertEqual(result.not_engineering, 1)


if __name__ == "__main__":
    unittest.main()

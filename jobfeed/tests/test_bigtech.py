import json
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from jobfeed import board, classify, sources
from jobfeed.storage import DirStore


class AmazonTests(unittest.TestCase):
    def test_reads_every_page(self):
        page = lambda n, total: {  # noqa: E731
            "hits": total,
            "jobs": [
                {
                    "id_icims": f"{n}{i}",
                    "title": "Software Development Engineer",
                    "normalized_location": "London, England, GBR",
                    "job_path": f"/en/jobs/{n}{i}/sde",
                    "posted_date": "November 10, 2026",
                    "job_category": "Software Development",
                    "description_short": "<p>Build &amp; ship.</p>",
                }
                for i in range(100 if n == 0 else 5)
            ],
        }
        with mock.patch.object(sources, "get_json", side_effect=[page(0, 105), page(1, 105)]) as get, \
                mock.patch.object(sources.time, "sleep"):
            roles = sources.fetch("amazon", "GBR")

        self.assertEqual(len(roles), 105)
        self.assertIn("offset=100", get.call_args_list[1].args[0])
        role = roles[0]
        self.assertEqual(role.url, "https://www.amazon.jobs/en/jobs/00/sde")
        self.assertEqual(role.posted_at, datetime(2026, 11, 10, tzinfo=timezone.utc))
        self.assertEqual(role.description, "Build & ship.")
        self.assertTrue(classify.is_uk(role))
        self.assertEqual(classify.work_type(role.title, role.department), "engineering")


class WorkdayTests(unittest.TestCase):
    FACETS = {
        "total": 2500,
        "jobPostings": [],
        "facets": [
            {"facetParameter": "jobFamilyGroup", "values": [{"descriptor": "Engineering", "id": "eng"}]},
            {
                "facetParameter": "locationMainGroup",
                "values": [
                    {"facetParameter": "locationHierarchy1", "descriptor": "Locations",
                     "values": [{"descriptor": "Armenia", "id": "am"}, {"descriptor": "United Kingdom", "id": "uk-id"}]},
                ],
            },
        ],
    }
    PAGE = {
        "total": 2,
        "jobPostings": [
            {"title": "Senior System Software Engineer", "externalPath": "/job/UK-Bristol/Senior-System-Software-Engineer_JR1",
             "locationsText": "2 Locations", "postedOn": "Posted 3 Days Ago", "bulletFields": ["JR1"]},
            {"title": "Solution Architect", "externalPath": "/job/UK-Remote/Solution-Architect_JR2",
             "locationsText": "UK, Remote", "postedOn": "Posted Today", "bulletFields": ["JR2"]},
        ],
    }

    def test_finds_the_nested_uk_filter_and_reads_roles(self):
        with mock.patch.object(sources, "get_json", side_effect=[self.FACETS, self.PAGE]) as get, \
                mock.patch.object(sources.time, "sleep"):
            roles = sources.fetch("workday", "nvidia.wd5:nvidia:NVIDIAExternalCareerSite")

        self.assertEqual(get.call_args_list[1].args[1]["appliedFacets"], {"locationHierarchy1": ["uk-id"]})
        self.assertEqual([r.source_id for r in roles], ["workday:nvidia:JR1", "workday:nvidia:JR2"])
        self.assertEqual(roles[0].location, "Bristol, UK")
        self.assertEqual(roles[1].workplace, "remote")
        self.assertTrue(roles[0].url.startswith("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/"))
        self.assertTrue(all(classify.is_uk(r) for r in roles))

    def test_no_uk_filter_means_no_roles(self):
        facets = {"facets": [{"facetParameter": "locationHierarchy1", "values": [{"descriptor": "France", "id": "fr"}]}]}
        with mock.patch.object(sources, "get_json", return_value=facets):
            self.assertEqual(sources.fetch("workday", "x.wd1:x:Site"), [])

    def test_posted_text(self):
        now = datetime(2026, 11, 17, tzinfo=timezone.utc)
        self.assertEqual(sources._workday_posted("Posted Today", now), now)
        self.assertEqual(sources._workday_posted("Posted 30+ Days Ago", now).day, 18)
        self.assertIsNone(sources._workday_posted("", now))


def apple_page(results, total):
    state = {"loaderData": {"search": {"searchResults": results, "totalRecords": total}}}
    encoded = json.dumps(json.dumps(state))
    return f"<script>window.__staticRouterHydrationData = JSON.parse({encoded});</script>"


APPLE_JOB = {
    "positionId": "200692188",
    "postingTitle": "Senior Production Designer ",
    "transformedPostingTitle": "senior-production-designer",
    "postDateInGMT": "2026-11-17T09:59:38.187949694Z",
    "jobSummary": "Design the look of international content.",
    "team": {"teamName": "Design"},
    "homeOffice": False,
    "locations": [{"city": "London", "name": "London", "countryName": "United Kingdom"}],
}


class AppleTests(unittest.TestCase):
    def test_reads_embedded_results_across_pages_without_duplicates(self):
        second = {**APPLE_JOB, "positionId": "1", "postingTitle": "UK - Specialist", "locations": [
            {"city": "", "name": "United Kingdom", "countryName": "United Kingdom"}]}
        pages = [apple_page([APPLE_JOB], 3), apple_page([APPLE_JOB, second], 3), apple_page([], 3)]
        with mock.patch.object(sources, "get_text", side_effect=pages) as get, mock.patch.object(sources.time, "sleep"):
            roles = sources.fetch("apple", "united-kingdom-GBR")

        self.assertIn("sort=newest", get.call_args_list[0].args[0])
        self.assertEqual(len(roles), 2)
        role = roles[0]
        self.assertEqual(role.title, "Senior Production Designer")
        self.assertEqual(role.location, "London, United Kingdom")
        self.assertEqual(roles[1].location, "United Kingdom")
        self.assertEqual(role.url, "https://jobs.apple.com/en-gb/details/200692188/senior-production-designer")
        self.assertEqual(classify.work_type(role.title, role.department), "design")

    def test_a_changed_page_is_an_error_not_an_empty_list(self):
        with mock.patch.object(sources, "get_text", return_value="<html>new design</html>"):
            with self.assertRaises(sources.SourceError):
                sources.fetch("apple", "united-kingdom-GBR")


class LinkOnlyTests(unittest.TestCase):
    def test_link_only_companies_are_listed_without_fetching(self):
        store = DirStore(tempfile.mkdtemp())
        store.write("static/logos/google.png", b"png", "image/png", "")
        companies = [{"name": "Google", "industry": "magnificent-7", "ats": "link",
                      "careers_url": "https://careers.example/uk", "website": "https://about.google"}]
        with mock.patch.object(board, "fetch") as fetch:
            result = board.build(store, companies)

        fetch.assert_not_called()
        self.assertEqual(result.kept, [])
        data = json.loads(store.read(board.BOARD_KEY))
        self.assertEqual(data["companies"][0]["careers_url"], "https://careers.example/uk")
        self.assertEqual(data["listings"], [])

    def test_link_only_needs_an_https_careers_url(self):
        path = tempfile.mktemp(suffix=".json")
        with open(path, "w") as handle:
            json.dump([{"name": "X", "industry": "ai", "ats": "link", "website": "https://x.example",
                        "careers_url": "javascript:alert(1)"}], handle)
        with self.assertRaisesRegex(ValueError, "https"):
            board.load_companies(board.Path(path))


if __name__ == "__main__":
    unittest.main()

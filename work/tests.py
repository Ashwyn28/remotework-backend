import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from work.jobsources import Role, SourceError, plain_text, salary_text
from work.jobsources import classify
from work.jobsources.sync import sync
from work.models import Company, Listing


def role(**overrides) -> Role:
    values = dict(
        source_id="greenhouse:acme:1",
        title="Senior Backend Engineer",
        location="London, United Kingdom",
        department="Engineering",
        url="https://boards.example/acme/1",
        apply_url="https://boards.example/acme/1",
        posted_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        workplace="hybrid",
        country="",
        salary="",
        description="Build things.",
    )
    values.update(overrides)
    return Role(**values)


class ClassifyTests(SimpleTestCase):
    def test_uk_locations(self):
        self.assertTrue(classify.is_uk(role(location="London, United Kingdom")))
        self.assertTrue(classify.is_uk(role(location="Cardiff, London or Remote (UK)")))
        self.assertTrue(classify.is_uk(role(location="Remote", country="GB")))
        self.assertTrue(classify.is_uk(role(location="Remote - EMEA", workplace="remote")))
        self.assertFalse(classify.is_uk(role(location="New York, NY")))
        self.assertFalse(classify.is_uk(role(location="US Remote", workplace="remote", country="United States")))
        self.assertFalse(classify.is_uk(role(location="Europe", workplace="onsite")))
        # "uk" must be a whole word
        self.assertFalse(classify.is_uk(role(location="Ukraine")))

    def test_work_type(self):
        cases = {
            "Senior Backend Engineer": "engineering",
            "Data Engineer": "data",
            "Analytics Engineering Manager, FinCrime": "data",
            "Senior Financial Control Analyst": "operations",
            "Product Analyst": "data",
            "Staff Product Designer (Retail)": "design",
            "Senior Product Manager": "product",
            "Product Engineer": "engineering",
            "Enterprise Account Executive": "sales",
            "Technology Account Partner - Banking": "sales",
            "Customer Success Manager": "sales",
            "Principal Product Marketing Manager": "marketing",
            "Office Manager": "operations",
            "Platform Engineer": "engineering",
            "GRC Engineer": "engineering",
            "Senior Credit Risk Manager, Credit Platform": "operations",
            "Platform Engineer, Payments": "engineering",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(classify.work_type(title), expected)

    def test_work_type_falls_back_to_department(self):
        self.assertEqual(classify.work_type("Member of Technical Staff", "Engineering"), "engineering")
        # a clearly non-technical title is not pulled in by its team's department
        self.assertEqual(classify.work_type("Procurement Lead", "Engineering"), "operations")
        self.assertEqual(classify.work_type("GRC Analyst", "Engineering"), "operations")
        self.assertEqual(classify.work_type("Associate", ""), "operations")

    def test_seniority(self):
        cases = {
            "Software Engineer - New Grad (2027 Start)": "junior",
            "Machine Learning Intern": "junior",
            "Software Engineer": "mid",
            "Senior Software Engineer": "senior",
            "Staff Software Engineer": "staff",
            "Principal Engineer": "staff",
            "Engineering Manager, Payments": "manager",
            "Head of Data": "manager",
            "Senior Manager, Customer Support": "manager",
            "Senior Product Manager": "senior",
            "Product Manager": "mid",
            "Account Manager": "mid",
            "Drones Operations Manager": "manager",
            "Senior Machine Learning Manager, Borrowing": "manager",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(classify.seniority(title), expected)

    def test_arrangement(self):
        self.assertEqual(classify.arrangement(role(workplace="remote")), "Remote")
        self.assertEqual(classify.arrangement(role(workplace="onsite")), "On-site")
        self.assertEqual(classify.arrangement(role(workplace="")), "")


class TextTests(SimpleTestCase):
    def test_plain_text_strips_escaped_markup(self):
        markup = "&lt;p&gt;Hello &amp;amp; welcome&lt;/p&gt;&lt;script&gt;x()&lt;/script&gt;"
        self.assertEqual(plain_text(markup), "Hello & welcome")

    def test_plain_text_is_cut_at_a_sentence(self):
        text = "First sentence here. " * 40
        result = plain_text(text, limit=100)
        self.assertTrue(result.endswith("."))
        self.assertLessEqual(len(result), 100)

    def test_salary_text(self):
        self.assertEqual(salary_text(80000, 100000, "GBP", "1 YEAR"), "£80k – £100k")
        self.assertEqual(salary_text(90000, 90000, "GBP"), "£90k")
        self.assertEqual(salary_text(150000, 200000, "USD", "1 YEAR"), "")
        self.assertEqual(salary_text(40, 60, "GBP", "1 HOUR"), "")
        self.assertEqual(salary_text(None, None, "GBP"), "")


class SyncTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Acme", email="careers@acme.invalid", is_top=True, ats="greenhouse", ats_slug="acme"
        )

    def run_sync(self, roles):
        with mock.patch("work.jobsources.sync.fetch", return_value=roles):
            return sync([self.company])

    def test_imports_uk_roles_only(self):
        result = self.run_sync([role(), role(source_id="greenhouse:acme:2", location="Austin, TX")])

        self.assertEqual((result.created, result.skipped), (1, 1))
        listing = Listing.objects.get()
        self.assertEqual(listing.category, "engineering")
        self.assertEqual(listing.seniority, "senior")
        self.assertEqual(listing.arrangement, "Hybrid")
        self.assertIsNotNone(listing.verified_at)

    def test_second_sync_updates_in_place_and_removes_closed_roles(self):
        self.run_sync([role(), role(source_id="greenhouse:acme:2", title="Data Engineer")])
        first_id = Listing.objects.get(source_id="greenhouse:acme:1").id

        result = self.run_sync([role(title="Staff Backend Engineer")])

        self.assertEqual((result.created, result.updated, result.removed), (0, 1, 1))
        listing = Listing.objects.get()
        self.assertEqual(listing.id, first_id)  # saved roles keep pointing at the same listing
        self.assertEqual(listing.seniority, "staff")

    def test_posted_roles_are_never_removed_by_a_sync(self):
        Listing.objects.create(company=self.company, job_title="Posted by hand", category="engineering", region="London")

        self.run_sync([])

        self.assertTrue(Listing.objects.filter(job_title="Posted by hand").exists())

    def test_unreachable_careers_site_keeps_existing_roles(self):
        self.run_sync([role()])
        with mock.patch("work.jobsources.sync.fetch", side_effect=SourceError("down")):
            result = sync([self.company])

        self.assertEqual(result.failed, ["Acme"])
        self.assertEqual(Listing.objects.count(), 1)


class BoardTests(TestCase):
    def test_board_lists_top_companies_roles_without_requiring_salary(self):
        top = Company.objects.create(name="Top", email="a@top.invalid", is_top=True)
        other = Company.objects.create(name="Other", email="a@other.invalid", is_top=False)
        Listing.objects.create(company=top, job_title="Engineer", category="engineering", region="London", seniority="mid")
        Listing.objects.create(company=other, job_title="Hidden", category="engineering", region="London")

        response = self.client.get("/board/")

        self.assertEqual(response.status_code, 200)
        titles = [item["job_title"] for item in response.json()]
        self.assertEqual(titles, ["Engineer"])
        self.assertEqual(response.json()[0]["seniority"], "mid")
        self.assertIsNone(response.json()[0]["company"]["logo"])


class LogoTests(TestCase):
    def setUp(self):
        from work import logos

        self.logos = logos
        self.dir = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(logos, "LOGO_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.company = Company.objects.create(name="Acme Bank", email="a@acme.invalid", website="https://acme.example")

    def test_fetches_the_best_icon_the_site_declares(self):
        page = b'<link rel="icon" href="/small.png"><link rel="apple-touch-icon" sizes="180x180" href="/big.png">'
        responses = {
            "https://acme.example": (page, "text/html"),
            "https://acme.example/big.png": (b"P" * 200, "image/png"),
        }
        with mock.patch("jobfeed.logos.get", side_effect=lambda url: responses[url]):
            source = self.logos.ensure_logo(self.company)

        self.assertEqual(source, "https://acme.example/big.png")
        self.assertEqual(self.logos.logo_filename(self.company), "acme-bank.png")

    def test_falls_back_to_the_usual_paths_when_the_page_declares_nothing(self):
        def get(url):
            if url == "https://acme.example/favicon.ico":
                return b"I" * 200, "image/x-icon"
            raise ValueError("not here")

        with mock.patch("jobfeed.logos.get", side_effect=get):
            self.assertEqual(self.logos.ensure_logo(self.company), "https://acme.example/favicon.ico")

    def test_keeps_an_existing_logo_unless_forced(self):
        (self.dir / "acme-bank.png").write_bytes(b"old")
        with mock.patch("jobfeed.logos.get") as get:
            self.assertIsNone(self.logos.ensure_logo(self.company))
            get.assert_not_called()

    def test_rejects_non_images_and_never_raises(self):
        with mock.patch("jobfeed.logos.get", return_value=(b"<html>" * 50, "text/html")):
            self.assertIsNone(self.logos.ensure_logo(self.company))
        self.assertIsNone(self.logos.logo_filename(self.company))

    def test_company_without_a_website_is_skipped(self):
        self.company.website = ""
        with mock.patch("jobfeed.logos.get") as get:
            self.assertIsNone(self.logos.ensure_logo(self.company))
            get.assert_not_called()

    def test_board_serves_the_saved_logo(self):
        self.company.is_top = True
        self.company.save()
        Listing.objects.create(company=self.company, job_title="Engineer", category="engineering", region="London")
        (self.dir / "acme-bank.svg").write_bytes(b"<svg/>")

        logo = self.client.get("/board/").json()[0]["company"]["logo"]

        self.assertEqual(logo, "/static/logos/acme-bank.svg")


class CompanyAdminLogoTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User

        from work import logos

        self.logos = logos
        self.dir = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(logos, "LOGO_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        admin_user = User.objects.create_superuser("admin", "admin@example.invalid", "test-only-password")
        self.client.force_login(admin_user)

    def test_adding_a_company_in_the_admin_fetches_its_logo(self):
        def get(url):
            if url == "https://newco.example/favicon.ico":
                return b"I" * 200, "image/x-icon"
            raise ValueError("not here")

        with mock.patch("jobfeed.logos.get", side_effect=get):
            response = self.client.post(
                reverse("admin:work_company_add"),
                {
                    "name": "NewCo",
                    "email": "jobs@newco.example",
                    "website": "https://newco.example",
                    "industry": "fintech",
                    "listings-TOTAL_FORMS": "0",
                    "listings-INITIAL_FORMS": "0",
                },
            )

        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["adminform"].errors)
        self.assertEqual(self.logos.logo_filename(Company.objects.get(name="NewCo")), "newco.ico")

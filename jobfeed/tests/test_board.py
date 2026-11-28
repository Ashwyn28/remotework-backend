import json
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from jobfeed import board
from jobfeed.sources import Role, SourceError
from jobfeed.storage import DirStore

NOW = datetime(2026, 11, 15, 6, 0, tzinfo=timezone.utc)
COMPANIES = [
    {"name": "Acme Bank", "industry": "fintech", "ats": "greenhouse", "board": "acme", "website": "https://acme.example"},
    {"name": "Robo Co", "industry": "robotics-and-deep-tech", "ats": "ashby", "board": "robo", "website": "https://robo.example"},
]


def role(source_id="greenhouse:acme:1", title="Senior Backend Engineer", location="London, United Kingdom", **extra):
    values = dict(
        source_id=source_id,
        title=title,
        location=location,
        department="Engineering",
        url=f"https://jobs.example/{source_id}",
        apply_url=f"https://jobs.example/{source_id}/apply",
        posted_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        workplace="hybrid",
        country="",
        salary="",
        description="Build things.",
    )
    values.update(extra)
    return Role(**values)


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.store = DirStore(tempfile.mkdtemp())
        # no network in tests: every company already has a logo unless a test says otherwise
        for stem in ("acme-bank", "robo-co"):
            self.store.write(f"static/logos/{stem}.png", b"png", "image/png", "")

    def build(self, roles_by_board):
        def fake_fetch(ats, name):
            result = roles_by_board[name]
            if isinstance(result, Exception):
                raise result
            return result

        with mock.patch.object(board, "fetch", side_effect=fake_fetch):
            return board.build(self.store, COMPANIES, now=NOW, workers=2)

    def board(self):
        return json.loads(self.store.read(board.BOARD_KEY))

    def test_writes_uk_roles_with_their_company(self):
        result = self.build({"acme": [role(), role("greenhouse:acme:2", location="Austin, TX")], "robo": []})

        data = self.board()
        self.assertEqual((result.roles, result.skipped), (1, 1))
        self.assertEqual(data["version"], board.FORMAT_VERSION)
        (listing,) = data["listings"]
        self.assertEqual(listing["company"], "acme-bank")
        self.assertEqual(listing["category"], "engineering")
        self.assertEqual(listing["seniority"], "senior")
        self.assertEqual(listing["arrangement"], "Hybrid")
        self.assertEqual(listing["verified_at"], "2026-11-15")
        companies = {c["id"]: c for c in data["companies"]}
        self.assertEqual(companies["acme-bank"]["logo"], "/static/logos/acme-bank.png")
        self.assertEqual(companies["robo-co"]["rank"], 1)

    def test_salaries_are_posted_or_estimated(self):
        long_text = "About us. " * 80 + "Salary: £70,000 – £90,000 + bonus."
        self.build({
            "acme": [
                role("greenhouse:acme:1", salary="£95k – £120k"),
                role("greenhouse:acme:2", description=long_text),
                role("greenhouse:acme:3"),
            ],
            "robo": [],
        })

        by_id = {row["id"]: row for row in self.board()["listings"]}
        posted, described, estimated = (by_id[board.role_id(f"greenhouse:acme:{n}")] for n in (1, 2, 3))
        self.assertEqual((posted["salary"], posted["salary_estimated"]), ("£95k – £120k", False))
        self.assertEqual((described["salary"], described["salary_estimated"]), ("£70k – £90k", False))
        self.assertLessEqual(len(described["description"]), 500)
        self.assertEqual((estimated["salary"], estimated["salary_estimated"]), ("£85k – £110k", True))

    def test_role_ids_are_stable_between_syncs(self):
        self.build({"acme": [role()], "robo": []})
        first = self.board()["listings"][0]["id"]
        self.build({"acme": [role(title="Staff Backend Engineer")], "robo": []})

        self.assertEqual(self.board()["listings"][0]["id"], first)
        self.assertRegex(first, r"^[0-9a-f]{16}$")

    def test_closed_roles_disappear(self):
        self.build({"acme": [role(), role("greenhouse:acme:2")], "robo": []})
        self.build({"acme": [role()], "robo": []})

        self.assertEqual(len(self.board()["listings"]), 1)

    def test_unreachable_company_keeps_yesterdays_roles(self):
        self.build({"acme": [role()], "robo": [role("ashby:robo:1", title="Robotics Engineer")]})

        result = self.build({"acme": [role()], "robo": SourceError("timed out")})

        self.assertEqual(result.kept, ["Robo Co"])
        titles = sorted(listing["job_title"] for listing in self.board()["listings"])
        self.assertEqual(titles, ["Robotics Engineer", "Senior Backend Engineer"])

    def test_duplicate_roles_are_listed_once(self):
        self.build({"acme": [role(), role()], "robo": []})

        self.assertEqual(len(self.board()["listings"]), 1)

    def test_fetches_missing_logos_once(self):
        COMPANIES_WITH_NEW = COMPANIES + [
            {"name": "New Co", "industry": "ai", "ats": "ashby", "board": "newco", "website": "https://new.example"}
        ]
        with mock.patch.object(board, "find_logo", return_value=(b"<svg/>", "svg", "https://new.example/i.svg")) as find, \
                mock.patch.object(board, "fetch", return_value=[]):
            result = board.build(self.store, COMPANIES_WITH_NEW, now=NOW)
            board.build(self.store, COMPANIES_WITH_NEW, now=NOW)

        self.assertEqual(result.new_logos, ["New Co"])
        self.assertEqual(find.call_count, 1)
        self.assertEqual(self.store.read("static/logos/new-co.svg"), b"<svg/>")

    def test_company_list_is_checked(self):
        path = tempfile.mktemp(suffix=".json")
        with open(path, "w") as handle:
            json.dump([{"name": "No Website", "industry": "ai", "ats": "ashby", "board": "x"}], handle)
        with self.assertRaisesRegex(ValueError, "website"):
            board.load_companies(board.Path(path))

    def test_curated_company_list_is_valid(self):
        companies = board.load_companies()
        self.assertGreater(len(companies), 50)


class DirStoreTests(unittest.TestCase):
    def test_keys_cannot_escape_the_folder(self):
        store = DirStore(tempfile.mkdtemp())
        with self.assertRaises(ValueError):
            store.write("../outside.txt", b"x", "text/plain", "")

    def test_lists_by_prefix(self):
        store = DirStore(tempfile.mkdtemp())
        store.write("static/logos/a.png", b"x", "image/png", "")
        store.write("data/board.json", b"{}", "application/json", "")
        self.assertEqual(store.keys("static/logos/"), ["static/logos/a.png"])
        self.assertEqual(store.read("missing.json"), None)


if __name__ == "__main__":
    unittest.main()

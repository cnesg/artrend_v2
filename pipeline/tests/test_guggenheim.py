import unittest
from pathlib import Path

from artrend_mag.sources import am_programs
from artrend_mag.sources._common import parse_date_range


class GuggenheimRenderedListingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        fixture = root / "work" / "dev" / "GuggenheimDOM" / "listing.html"
        cls.html = fixture.read_text(encoding="utf-8")
        cls.records, cls.venue = am_programs._guggenheim_events(
            cls.html, "https://www.guggenheim.org/exhibitions")

    def test_captured_listing_has_on_view_and_past_exhibitions(self):
        self.assertEqual(len(self.records), 14)
        self.assertEqual(sum(record["section"] == "Exhibitions On View" for record in self.records), 4)
        self.assertEqual(sum(record["section"] == "Past Exhibitions" for record in self.records), 10)
        self.assertEqual(self.venue, "1071 Fifth Avenue, New York, NY 10128")

    def test_dates_are_from_displayed_card_text(self):
        events = {record["slug"]: record for record in self.records}
        cases = {
            "taryn-simon": ("2026-09-18", "day", "2027-03-14", "day"),
            "guggenheim-pop": ("2026-06-05", "day", "2027-01-10", "day"),
            "carol-bove": ("2026-03-05", "day", "2026-08-02", "day"),
            "rashid-johnson-a-poem-for-deep-thinkers":
                ("2025-04-18", "day", "2026-01-19", "day"),
        }
        for slug, expected in cases.items():
            with self.subTest(slug=slug):
                self.assertEqual(parse_date_range(events[slug]["date_text"]), expected)

    def test_ongoing_collection_has_no_invented_dates(self):
        thannhauser = next(record for record in self.records if record["slug"] == "thannhauser-collection")
        self.assertEqual(thannhauser["date_text"], "Ongoing")
        self.assertEqual(parse_date_range(thannhauser["date_text"]), (None, None, None, None))

    def test_public_past_archive_link_is_exposed(self):
        from artrend_mag.sources._common import soup

        page = soup(self.html)
        self.assertEqual(am_programs._guggenheim_past_url(page, "https://www.guggenheim.org/exhibitions"),
                         "https://www.guggenheim.org/exhibitions/past")


if __name__ == "__main__":
    unittest.main()

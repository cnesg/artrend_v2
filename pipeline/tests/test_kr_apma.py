import unittest

from bs4 import BeautifulSoup

from artrend_mag.sources.kr_apma import _date_and_location, _event_key, _parse_date_range


class APMAParserTests(unittest.TestCase):
    def test_spaced_sol_lewitt_schedule_markup(self):
        content = BeautifulSoup(
            '<div id="contents"><ul><li class="place">'
            '2026. 09. 01. (화) - 2027. 02. 28. (일) | 미술관 1F로비, B1 1~7전시실, 교육실 등'
            '</li></ul></div>',
            "lxml",
        ).select_one("#contents")

        date_text, location = _date_and_location(content)

        self.assertEqual(date_text, "2026. 09. 01. (화) - 2027. 02. 28. (일)")
        self.assertEqual(location, "미술관 1F로비, B1 1~7전시실, 교육실 등")
        self.assertEqual(_parse_date_range(date_text),
                         ("2026-09-01", "day", "2027-02-28", "day"))

    def test_compact_chapter_five_schedule_markup(self):
        content = BeautifulSoup(
            '<div id="contents"><ul><li class="place">'
            '2026.04.01(수) – 2026.08.02(일) | 미술관 1F로비, B1 1~7전시실, 교육실 등'
            '</li></ul></div>',
            "lxml",
        ).select_one("#contents")

        date_text, location = _date_and_location(content)

        self.assertEqual(date_text, "2026.04.01(수) – 2026.08.02(일)")
        self.assertEqual(_parse_date_range(date_text),
                         ("2026-04-01", "day", "2026-08-02", "day"))
        self.assertIn("미술관", location)

    def test_dedup_requires_same_title_dates_and_venue(self):
        same = _event_key("Sol LeWitt: Open Structure", "2026-09-01", "day", "2027-02-28", "day",
                          "미술관 1F로비", "4229692")
        duplicate_article = _event_key("Sol LeWitt: Open Structure", "2026-09-01", "day", "2027-02-28", "day",
                                       "미술관 1F로비", "4210423")
        next_edition = _event_key("Sol LeWitt: Open Structure", "2027-09-01", "day", "2028-02-28", "day",
                                  "미술관 1F로비", "next-edition")
        title_variant = _event_key("APMA, CHAPTER FIVE: FROM THE APMA COLLECTION", "2026-04-01", "day",
                                   "2026-08-02", "day", "미술관 1F로비", "4055621")

        self.assertEqual(same, duplicate_article)
        self.assertNotEqual(same, next_edition)
        self.assertNotEqual(_event_key("APMA, CHAPTER FIVE", "2026-04-01", "day", "2026-08-02", "day",
                                      "미술관 1F로비", "4109060"), title_variant)
        self.assertNotEqual(_event_key("Unknown", "2026-04-01", "day", "2026-08-02", "day", None, "a"),
                            _event_key("Unknown", "2026-04-01", "day", "2026-08-02", "day", None, "b"))


if __name__ == "__main__":
    unittest.main()

import unittest

from artrend_mag.sources.kr_kiaf import SOURCES, _parse_editions


class KiafRenderedParserTests(unittest.TestCase):
    def test_info_page_extracts_fair_edition_only_from_visible_year_dates_and_venue(self):
        html = '''
        <div class="row section"><div class="col-12">
          <div class="title">Kiaf SEOUL 2026</div>
          <div class="title-desc">서울 코엑스 (coex) Hall A, B, Grand Ballroom<br/>
            2026.9.2 - 9.6
          </div>
        </div></div>
        '''

        editions = _parse_editions(html, "https://kiaf.org/info")

        self.assertEqual(len(editions), 1)
        self.assertEqual(editions[0]["title"], "Kiaf SEOUL 2026")
        self.assertEqual(editions[0]["date_text"], "2026.9.2 - 9.6")
        self.assertEqual(editions[0]["start"], "2026-09-02")
        self.assertEqual(editions[0]["start_precision"], "day")
        self.assertEqual(editions[0]["end"], "2026-09-06")
        self.assertEqual(editions[0]["end_precision"], "day")
        self.assertEqual(editions[0]["city"], "Seoul")
        self.assertEqual(editions[0]["country_code"], "KR")
        self.assertEqual(editions[0]["url"], "https://kiaf.org/info")

    def test_no_fair_event_without_visible_date_range_or_venue(self):
        missing_date = '''<div class="row section"><div class="col-12">
          <div class="title">Kiaf SEOUL 2026</div><div class="title-desc">COEX Seoul</div>
        </div></div>'''
        missing_venue = '''<div class="row section"><div class="col-12">
          <div class="title">Kiaf SEOUL 2026</div><div class="title-desc">2026.9.2 - 9.6</div>
        </div></div>'''

        self.assertEqual(_parse_editions(missing_date, "https://kiaf.org/info"), [])
        self.assertEqual(_parse_editions(missing_venue, "https://kiaf.org/info"), [])

    def test_one_fair_edition_per_visible_year(self):
        section = '''<div class="row section"><div class="col-12">
          <div class="title">Kiaf SEOUL 2026</div>
          <div class="title-desc">Seoul COEX 2026.9.2 - 9.6</div>
        </div></div>'''

        editions = _parse_editions(section + section, "https://kiaf.org/info")

        self.assertEqual(len(editions), 1)
        self.assertEqual(editions[0]["year"], 2026)

    def test_stable_kiaf_source_id_and_terms_record(self):
        self.assertEqual(len(SOURCES), 1)
        self.assertEqual(SOURCES[0]["source_id"], "kiaf_seoul")
        self.assertEqual(SOURCES[0]["blueprint_data_id"], "D23")
        self.assertEqual(SOURCES[0]["terms_url"], "https://kiaf.org/terms-conditions")


if __name__ == "__main__":
    unittest.main()

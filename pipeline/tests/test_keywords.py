import datetime as dt
import unittest

from artrend_mag import keywords

D = dt.date(2026, 11, 4)


class FakeVB:
    def __init__(self, stories, events=None):
        self._stories, self.events, self.asof = stories, events or {}, D

    def stories(self, scope, lo, hi, report_day):
        return self._stories

    def ko_of(self, table, key, field, text):
        return None

    def is_specialist(self, a):
        return False

    def source_label(self, a, bare=False):
        return a["publisher"]


def story(title, outlet, days_ago, n=0):
    a = dict(article_id=f"{title}{outlet}{n}", title=title, publisher=outlet, canonical_url=f"https://x/{n}{outlet}",
             published_at=(D - dt.timedelta(days=days_ago)).isoformat())
    return dict(lead=a, members=[a], outlets=[outlet])


def baseline(n=200):
    """Four quiet weeks of ordinary exhibition news."""
    return [story(f"작가 개인전 개최 {i}", f"base{i % 9}", 8 + i % 27, i) for i in range(n)]


class HotKeywordTests(unittest.TestCase):
    def labels(self, stories, people=None):
        return [k["label"] for k in keywords.hot(FakeVB(stories), "KR", D, people)]

    def test_rising_concept_from_several_outlets_is_a_trend(self):
        week = [story(f"섬유 작업 전시 {i}", f"o{i}", i % 5, 1000 + i) for i in range(4)]
        out = keywords.hot(FakeVB(baseline() + week), "KR", D)
        k = next(k for k in out if k["label"] == "섬유·직조")
        self.assertEqual(k["n"], 4)
        self.assertEqual(k["rise"], "새로 등장")
        self.assertEqual(len(k["examples"]), 3)

    def test_one_outlet_repeating_itself_is_not_a_trend(self):
        week = [story(f"섬유 작업 전시 {i}", "same", i % 5, 1000 + i) for i in range(5)]
        self.assertNotIn("섬유·직조", self.labels(baseline() + week))

    def test_a_word_that_is_always_there_is_not_a_trend(self):
        base = [story(f"회화 전시 {i}", f"b{i % 9}", 8 + i % 27, i) for i in range(200)]
        week = [story(f"회화 전시 {i}", f"o{i}", i % 5, 1000 + i) for i in range(10)] + baseline(40)[:30]
        self.assertNotIn("회화", self.labels(base + week))

    def test_bylines_and_sports_do_not_count(self):
        week = [story(f"미술관 소식 (사진=연합뉴스) {i}", f"o{i}", 1, 1000 + i) for i in range(5)]
        week += [story(f"파크골프대회 개인전 장애인 우승 {i}", f"p{i}", 1, 2000 + i) for i in range(5)]
        labels = self.labels(baseline() + week)
        self.assertNotIn("사진", labels)
        self.assertNotIn("장애·접근성", labels)

    def test_named_event_is_found_but_clause_fragments_are_not(self):
        week = [story(f"'아트에디션 아트페어 2026' 개막 {i}", f"o{i}", 1, 1000 + i) for i in range(3)]
        week += [story(f"작품을 볼 수 있는 아트페어 전시 {i}", f"q{i}", 1, 2000 + i) for i in range(3)]
        labels = self.labels(baseline() + week)
        self.assertIn("아트에디션 아트페어", labels)
        self.assertFalse(any(l.startswith("있는") for l in labels))

    def test_people_need_full_names_and_two_signals(self):
        people = [dict(name="유영", press=5, shows=1), dict(name="홍진훤", press=3, shows=0), dict(name="Anselm Kiefer", press=1, shows=1),
                  dict(name="Kiefer", press=4, shows=0), dict(name="김철수", press=1, shows=0)]
        labels = self.labels(baseline(), people)
        self.assertEqual([l for l in labels if l in {"유영", "홍진훤", "Anselm Kiefer", "Kiefer", "김철수"}], ["홍진훤", "Anselm Kiefer"])

    def test_tags_for_matches_concepts_and_names(self):
        kws = [dict(label="도자·공예"), dict(label="홍진훤")]
        self.assertEqual(keywords.tags_for("경기도자비엔날레 32만 명", kws), ["도자·공예"])
        self.assertEqual(keywords.tags_for("홍진훤, 올해의 작가상", kws), ["홍진훤"])


if __name__ == "__main__":
    unittest.main()

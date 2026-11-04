import collections
import datetime as dt
import unittest

from artrend_mag.daily_trend import Trend

D = dt.date(2026, 10, 30)


class FakeVB:
    def __init__(self, events, sources):
        self.events = {e["event_id"]: e for e in events}
        self.sources = sources
        self.entities = {"ent_a": dict(canonical_name="A", entity_type="person")}
        self.participants = collections.defaultdict(list)

    def event_link(self, eid):
        return eid

    def entity_link(self, eid, name=None):
        return name or eid

    def reading(self, scope, lo, hi):
        return []


def ev(i, start, src="g1", city="Seoul"):
    return dict(event_id=f"e{i}", source_id=src, event_type="exhibition", edition_region="KR", start_date=start,
                start_precision="day", end_date=None, city=city, organizer_entity_id=None, announced_date=None, title=f"t{i}")


class TrendTests(unittest.TestCase):
    sources = {"g1": dict(source_kind="gallery", name="G1"), "m1": dict(source_kind="museum", name="M1")}

    def test_thin_baseline_does_not_claim_a_surge(self):
        vb = FakeVB([ev(1, "2026-10-28"), ev(2, "2026-10-29", "m1"), ev(3, "2026-10-10")], self.sources)
        o = Trend(vb, "KR", D).exhibitions()
        self.assertIn("비교 보류", o["fact"])
        self.assertNotIn("몰린", o["read"])
        self.assertIn("갤러리 1 · 미술관·기관 1", o["fact"])

    def test_surge_against_a_real_baseline(self):
        base = [ev(10 + i, (D - dt.timedelta(days=8 + (i % 26))).isoformat()) for i in range(16)]  # 4/week
        week = [ev(30 + i, "2026-10-29", f"s{i % 4}") for i in range(10)]  # spread over four organizers
        o = Trend(FakeVB(base + week, self.sources), "KR", D).exhibitions()
        self.assertIn("+150%", o["fact"])
        self.assertIn("몰린", o["read"])
        self.assertIn("붐빈다", o["title"])

    def test_one_organizer_is_the_story_not_the_city(self):
        base = [ev(10 + i, (D - dt.timedelta(days=8 + (i % 26))).isoformat()) for i in range(16)]
        week = [ev(30 + i, "2026-10-29", "m1") for i in range(4)] + [ev(40, "2026-10-28")]
        week[0]["title"] = "Rookie Award 2026 Grand Prize Exhibition"
        o = Trend(FakeVB(base + week, self.sources), "KR", D).exhibitions()
        self.assertNotIn("붐빈다", o["title"])
        self.assertTrue(o["title"].startswith("M1, ") and "전시" in o["title"])
        self.assertIn("4개 중", o["dek"].replace("5개 중 4개", "4개 중"))
        self.assertIn("org:M1", o["keys"])
        self.assertIn("bridge", o["keys"])  # the award show is already told here

    def test_artist_seen_in_exhibition_and_press(self):
        vb = FakeVB([ev(1, "2026-10-20")], self.sources)
        vb.participants["e1"] = [dict(entity_id="ent_a", name_as_listed="A", role="artist")]
        stories = [dict(names=[("A", "ent_a")], lead=dict(article_id="x", title="A 개인전"), outlets=["o1", "o2", "o3"],
                        members=[dict(title="A 개인전")])]
        o = Trend(vb, "KR", D).artists_axis(stories)
        self.assertIn("전시와 보도에 함께 나온 작가 1명", o["fact"])
        self.assertTrue(o["title"].startswith("A, "))
        self.assertTrue(o["dek"].endswith("."))

    def test_widely_covered_name_leads_even_without_exhibition(self):
        vb = FakeVB([], self.sources)
        vb.entities["ent_b"] = dict(canonical_name="B", entity_type="person")
        stories = [dict(names=[("B", "ent_b")], lead=dict(article_id="y", title="B, 올해의 작가상"), outlets=[f"o{i}" for i in range(12)],
                        members=[dict(title="B, 올해의 작가상")])]
        o = Trend(vb, "KR", D).artists_axis(stories)
        self.assertEqual(o["power"], 3)
        self.assertIn("가장 많이 불린 이름", o["title"])

    def test_gallery_feed_routing(self):
        self.assertEqual(Trend.route("Featured in The Hankyoreh: Anselm Kiefer"), "KR")
        self.assertEqual(Trend.route("New show in London and Paris"), "EUROPE")
        self.assertEqual(Trend.route("Opening in New York"), "AMERICAS")


if __name__ == "__main__":
    unittest.main()


class WordingTests(unittest.TestCase):
    def test_josa_and_short_titles(self):
        from artrend_mag.daily_trend import josa, short
        self.assertEqual(josa("미술관"), "미술관이")
        self.assertEqual(josa("갤러리"), "갤러리가")
        self.assertEqual(short("제16회 광주비엔날레 《You Must Change Your Life》", 30), "제16회 광주비엔날레")


class InsightTests(unittest.TestCase):
    sources = {"g1": dict(source_kind="gallery", name="G1"), "g2": dict(source_kind="gallery", name="G2"),
               "m1": dict(source_kind="museum", name="M1")}

    def test_theme_needs_two_shows_from_different_places(self):
        one = FakeVB([ev(1, "2026-10-29", "g1")], self.sources)
        one.events["e1"]["title"] = "Glacier Diary"
        self.assertEqual(Trend(one, "KR", D).themes([]), [])
        two = FakeVB([ev(1, "2026-10-29", "g1"), ev(2, "2026-10-30", "g2")], self.sources)
        two.events["e1"]["title"], two.events["e2"]["title"] = "Glacier Diary", "OCEAN"
        out = Trend(two, "KR", D).themes([])
        self.assertEqual(out[0]["title"], "이번 주 전시 키워드: 기후와 자연")
        self.assertIn("전시 2곳", out[0]["dek"])

    def test_press_alone_never_makes_a_theme(self):
        vb = FakeVB([], self.sources)
        stories = [dict(lead=dict(article_id=f"a{i}", title=f"사진전 {i}"), outlets=["o1", "o2"], members=[dict(title=f"사진전 {i}")])
                   for i in range(10)]
        self.assertEqual(Trend(vb, "KR", D).themes(stories), [])

    def test_short_latin_keyword_matches_before_hangul(self):
        from artrend_mag.daily_trend import THEME_RX
        self.assertTrue(THEME_RX["tech"].search("AI와 예술"))
        self.assertFalse(THEME_RX["tech"].search("Thailand"))

    def test_award_show_bridge(self):
        vb = FakeVB([ev(1, "2026-11-03", "m1")], self.sources)
        vb.events["e1"]["title"] = "제26회 이인성미술상 수상자전"
        o = Trend(vb, "KR", D).bridge()
        self.assertTrue(o["title"].startswith("이인성미술상 수상작, M1에 걸린다"))
        self.assertTrue(o["dek"].startswith("11월 3일"))

    def test_echo_skips_one_gallery_branches(self):
        a = ev(1, "2026-10-28", "g1", "Seoul")
        b = dict(ev(2, "2026-10-29", "g1", "London"), edition_region="EUROPE")
        vb = FakeVB([a, b], self.sources)
        for e in ("e1", "e2"):
            vb.participants[e] = [dict(entity_id="ent_a", name_as_listed="A", role="artist")]
        self.assertIsNone(Trend(vb, "KR", D).echo())
        vb.events["e2"]["source_id"] = "g2"
        o = Trend(vb, "KR", D).echo()
        self.assertEqual(o["title"], "A, 서울·런던 동시 전시")

    def test_ranked_keeps_one_headline_per_subject(self):
        from artrend_mag.daily_trend import ranked
        obs = [dict(axis="갤러리", power=2, title="g", keys=["org:X"]), dict(axis="전시", power=2, title="e", keys=["org:X"]),
               dict(axis="보도", power=3, title="p")]
        self.assertEqual([o["title"] for o in ranked(obs)], ["p", "e"])


class FreshnessTests(unittest.TestCase):
    def test_a_subject_that_already_led_steps_aside_unless_renewed(self):
        import datetime as dt
        from artrend_mag.daily_trend import freshen
        d = dt.date(2026, 11, 3)
        old = dict(axis="화제", title="A", power=3, keys=["name:A"], latest="2026-10-28")
        new = dict(axis="전시", title="B", power=2, keys=["org:B"], latest="2026-11-03")
        filler = dict(axis="보도", title="C", power=1, keys=["story:C"], latest=None)
        out = freshen([old, new, filler], {"name:A": 2}, d)
        self.assertEqual([o["title"] for o in out], ["B", "A", "C"])  # stepped aside, still above a quiet-week filler
        renewed = dict(old, latest="2026-11-03")
        self.assertEqual(freshen([renewed, new], {"name:A": 2}, d)[0]["title"], "A")

import datetime as dt
import unittest

from artrend_mag import editorial as ed

ASOF = dt.date(2026, 10, 30)


def h(date, title, kinds, key=None):
    return dict(date=date, title=title, url="u" + title, publisher="p", kinds=kinds, event_key=key)


class AwardWeightTests(unittest.TestCase):
    def test_public_juried_award_with_followup_is_high(self):
        w = ed.award_weight(dict(organizer="홍성군", organizer_type="국공립 미술관·지자체", since=2012,
                                 selection="공모 162명 → 전문가 5명 심층 심사", rewards=["상금 2,000만원", "2027년 개인전"]), ASOF)
        self.assertEqual(w["level"], "높음")
        self.assertTrue(any("상금" in r for r in w["reasons"]))

    def test_commercial_contest_is_excluded(self):
        w = ed.award_weight(dict(organizer="KPAM", organizer_type="상업 공모전·방송사", rewards=["부스전"]), ASOF)
        self.assertEqual(w["level"], "제외")


class AssessTests(unittest.TestCase):
    award = dict(title="2027 우진청년미술상", n_outlets=4, support=["창작지원금 500만원", "초대전"], date="2026-10-26")

    def test_same_award_reports_do_not_count_as_independent_events(self):
        hist = [h("2026-10-26", "우진청년미술상에 김승주 작가 선정", ["award"], "우진청년미술상"),
                h("2026-09-01", "2027 우진청년미술상 후보 김승주 작가", ["award"], None),
                h("2022-10-11", "김승주 조각전 개인전 향교길68", ["solo"], None)]
        c = ed.assess("김승주", self.award, hist, [], ASOF)
        r03 = next(x for x in c["checks"] if x["rule"].startswith("R03"))
        self.assertFalse(r03["ok"])
        self.assertEqual(c["status"], "관찰 후보")

    def test_seventh_solo_show_flags_mid_career(self):
        hist = [h("2026-03-19", "임희성 개인전 '삶의 풍경'", ["solo"], "삶의 풍경"),
                h("2020-12-16", "임희성 작가 일곱번째 개인전", ["solo"], None)]
        c = ed.assess("임희성", self.award, hist, [], ASOF)
        self.assertEqual(c["status"], "재발견·중견 확인 필요")

    def test_homonym_articles_are_dropped_and_block_a_pass(self):
        hist = [h("2026-09-14", "배우 한소희 영화 '인턴' 출연", [], "인턴")] * 3 + [
            h("2026-07-24", "단원미술제 선정작가 한소희", ["award"], None), h("2026-05-02", "한소희 작가 단체전 참여 전시", ["group"], None)]
        c = ed.assess("한소희", dict(self.award, title="제27회 단원미술제"), hist, [], ASOF)
        self.assertTrue(c["homonym_risk"])
        self.assertNotEqual(c["status"], "편집 검토 후보")

    def test_no_history_means_unknown_not_fail(self):
        c = ed.assess("窪田望", self.award, None, [], ASOF)
        r03 = next(x for x in c["checks"] if x["rule"].startswith("R03"))
        self.assertIsNone(r03["ok"])


class CriteriaTests(unittest.TestCase):
    def test_criteria_are_named_with_evidence(self):
        crit = ed.criteria_of(["서울시립미술관, 비엔날레 예술감독 선정", "국제 공모 70건 중 선정"], ASOF, 13, [])
        ids = {c["id"] for c in crit}
        self.assertTrue({"public", "award", "reach"} <= ids)
        self.assertTrue(all(c["evidence"] for c in crit))


if __name__ == "__main__":
    unittest.main()


class GlanceTests(unittest.TestCase):
    def test_glance_shows_insights_then_summary_and_so_what(self):
        from artrend_mag.frontpage_render import glance_lines
        notes = {"glance": {"KR": ["공공기관 결정 발표가 몰린 주."]},
                 "major": {"a": dict(edition="KR", rank=2, headline="B", summary="B 요약. 둘째 문장.", so_what="B 의미. 더.", why=[]),
                           "b": dict(edition="KR", rank=1, headline="A", brief="A 한 줄", summary="A 요약.", so_what="A 의미.", why=[]),
                           "c": dict(edition="KR", exclude=True, reason="인터뷰")}}
        text = "\n".join(glance_lines(notes, "KR"))
        self.assertLess(text.index("공공기관"), text.index("**A**"))
        self.assertLess(text.index("**A**"), text.index("**B**"))
        self.assertIn("A 한 줄", text)
        self.assertIn("B 요약.", text)
        self.assertNotIn("둘째 문장", text)
        self.assertIn("→ B 의미.", text)

    def test_no_notes_means_no_glance(self):
        from artrend_mag.frontpage_render import glance_lines
        self.assertEqual(glance_lines({}, "KR"), [])


class ForeignPrizeTests(unittest.TestCase):
    def test_foreign_currency_prize_counts(self):
        w = ed.award_weight(dict(organizer="Frieze", organizer_type="민간 재단·기업", rewards=["상금 £30,000"]), ASOF)
        self.assertTrue(any("£30,000" in r for r in w["reasons"]))
        w = ed.award_weight(dict(organizer="X", organizer_type="민간 재단·기업", rewards=["상금 €500"]), ASOF)
        self.assertFalse(any("€500" in r for r in w["reasons"]))


class AutoJudgementTests(unittest.TestCase):
    def story(self, title, excerpts, outlets=1, topic="exhibition"):
        members = [dict(title=title, excerpt=e, lang="ko") for e in excerpts]
        return dict(lead=members[0], members=members, outlets=["o%d" % i for i in range(outlets)], names=[], topic=topic)

    def test_volume_alone_is_not_importance(self):
        j = ed.auto_judgement(self.story("중랑구 미술인초대전 개최", ["중랑구가 미술인초대전을 연다고 밝혔다."], outlets=12),
                              dt.date(2026, 10, 29))
        self.assertIn("보도량만으로는", j["why"][0])
        self.assertEqual(j["level"], "짧은 소식")
        self.assertNotIn("기록용", j["so_what"])

    def test_public_policy_story_is_major_with_named_criteria(self):
        j = ed.auto_judgement(self.story("문체부, 미술품 감정서 고시 제정", ["문화체육관광부는 29일 감정서 양식을 고시했다."], outlets=10,
                                         topic="policy"), dt.date(2026, 10, 29))
        self.assertEqual(j["level"], "주요")
        self.assertIn("국가·공공 주체", j["why"][0])

    def test_summary_drops_duplicates_and_off_topic_sentences(self):
        s = ed.auto_summary(self.story("김해 두 미술관 평가인증 동반 인증", [
            "김해 두 미술관이 공립미술관 평가인증에서 동반 인증됐다고 27일 밝혔다.",
            "김해 두 미술관이 공립미술관 평가인증에서 동반 인증됐다고 27일 밝혔다.",
            "4위 김화숙, 5위 장정자가 각각 차지했다."]))
        self.assertEqual(s.count("동반 인증"), 1)
        self.assertNotIn("김화숙", s)


class ReaderTextTests(unittest.TestCase):
    def story(self, title, outlets=1, topic=None):
        return dict(lead=dict(title=title, lang="ko"), members=[dict(title=title, excerpt="")], outlets=[f"o{i}" for i in range(outlets)],
                    names=[], topic=topic)

    def test_hosting_at_a_national_museum_is_not_a_public_decision(self):
        j = ed.auto_judgement(self.story("국립현대미술관서 열린 미술 분과 회의", 3), dt.date(2026, 11, 1))
        self.assertNotIn("공공 결정", j["so_what"])
        j = ed.auto_judgement(self.story("문체부, 미술품 감정서 양식 고시", 3, "policy"), dt.date(2026, 11, 1))
        self.assertIn("공공 결정", j["so_what"])

    def test_record_is_not_called_a_first(self):
        j = ed.auto_judgement(self.story("모네 '붓꽃' 역대 최고가 낙찰", 2, "market"), dt.date(2026, 11, 1))
        self.assertNotIn("처음 시도", j["so_what"])

    def test_editor_jargon_is_removed_for_readers(self):
        from artrend_mag.web_export import reader_text
        self.assertEqual(reader_text("전시는 11일까지다. 작가 포커스(H02) 후보로 본다."), "전시는 11일까지다.")
        self.assertIsNone(reader_text("Rookie 대상이 아니다."))
        self.assertEqual(reader_text("퐁피두가 문을 닫는다. 기관 공식 발표로 확인한다."), "퐁피두가 문을 닫는다.")
        self.assertIsNone(reader_text("시장(M) 축의 제도 변화다."))

    def test_french_institution_change_counts(self):
        j = ed.auto_judgement(self.story("Pierre-Olivier Costa retrouve la présidence du Mucem", 1), dt.date(2026, 11, 1))
        self.assertNotEqual(j["level"], "짧은 소식")


class ReaderLeadTests(unittest.TestCase):
    def test_coverage_counts_are_not_reasons(self):
        from artrend_mag.web_export import clean_why
        self.assertEqual(clean_why(["법률에 근거한 정부 고시", "연합뉴스·KBS·SBS·YTN 등 10곳 이상이 각자 보도, 정책실장 발언 인용",
                                    "공식 선정·수상('수상') · 3개 매체 보도"]),
                         ["법률에 근거한 정부 고시", "공식 선정·수상('수상')"])

    def test_so_what_joins_the_lead_in_a_readers_voice(self):
        from artrend_mag.web_export import merge_lead
        out = merge_lead("감정서 양식이 고시됨 — 내년 7월까지 계도기간",
                         "계도기간 종료 전후로 감정서 발급 방식이 바뀌는지 본다. 가격 데이터가 아니라 제도로 MARKET CONTEXT에 넣는다.")
        self.assertEqual(out, "감정서 양식이 고시됨 — 내년 7월까지 계도기간. 계도기간 종료 전후로 감정서 발급 방식이 바뀌는지가 다음 관전 포인트다.")
        self.assertEqual(merge_lead("요약이다.", "큰 사건은 아니지만 이번 주 흐름을 보여 주는 소식이다."), "요약이다.")

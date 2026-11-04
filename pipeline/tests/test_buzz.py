import unittest

from artrend_mag import buzz


def story(titles, outlets, names=(), pub="2026-11-01"):
    return dict(lead=dict(article_id="a0", title=titles[0], published_at=pub), outlets=list(outlets), names=list(names),
                members=[dict(title=t) for t in titles])


PERSON = lambda eid: eid.startswith("p_")


class SlotTests(unittest.TestCase):
    def test_first_slots(self):
        self.assertEqual(buzz.first_slot("린 허쉬만 리슨 아시아 첫 미술관 개인전"), "아시아 첫 미술관 개인전")
        self.assertEqual(buzz.first_slot("Marks His First Solo Exhibition in Korea"), "국내 첫 개인전")
        self.assertEqual(buzz.first_slot("ディーター・ラムスの公式巡回展が日本初開催"), "일본 첫 전시")

    def test_heat_slots(self):
        self.assertEqual(buzz.heat_slot(["유영국 회고전 45만명 봤다…서울시립미술관 무료 전시 역대 최다"]), "45만 명이 찾았다 — 역대 최다")
        self.assertEqual(buzz.heat_slot(["티켓 6만 6000장 판매…BTS RM 파워"]), "입장권 6만 6000장이 팔렸다")
        self.assertEqual(buzz.heat_slot(["양주시 '장흥 미술관 여행' 통합이용권 1,000매 완판"]), "표가 동났다")
        self.assertEqual(buzz.heat_slot(["화가 박해룡, 첫 개인전 완판"]), "작품이 모두 팔렸다")
        self.assertEqual(buzz.heat_slot(["나는 나의 길로만 매진(邁進)했다"]), "")

    def test_record_slot(self):
        self.assertEqual(buzz.record_slot(["모네의 '붓꽃' 742억에 낙찰…프랑스 미술품 경매 최고가"]), "742억에 낙찰, 프랑스 경매 최고가")

    def test_route_by_place_not_by_name(self):
        self.assertEqual(buzz.route(["유영국 회고전 폐막, 누적 관람객 45만 명"]), None)  # '유영국' is not 영국
        self.assertEqual(buzz.route(["BTS RM, 샌프란시스코 현대미술관 6.6만 티켓"]), "AMERICAS")
        self.assertEqual(buzz.route(["대구미술관, 프랑스 현대미술가 '스테판 티데' 국내 첫 개인전"]), "KR")


class HeadlineTests(unittest.TestCase):
    def test_named_first_with_descriptor_and_venue(self):
        st = story(["대구미술관, 프랑스 현대미술가 '스테판 티데' 국내 첫 개인전 개최", "스테판 티데 국내 첫 개인전"], ["o1", "o2"])
        x = buzz.rank([st], PERSON, ["대구미술관"], "2026-11-01")[0]
        c = buzz.compose(x["a"], x["outlets"])
        self.assertEqual(c["title"], "프랑스 현대미술가 스테판 티데, 대구미술관에서 국내 첫 개인전")
        self.assertIn("처음 직접 만난다", c["dek"])

    def test_crowd_headline_uses_the_show(self):
        st = story(["유영국 회고전 45만명 봤다…서울시립미술관 무료 전시 역대 최다"], ["o1", "o2"])
        x = buzz.rank([st], PERSON, ["서울시립미술관"], "2026-11-01")[0]
        self.assertEqual(buzz.compose(x["a"], 2)["title"], "유영국 회고전, 서울시립미술관에서 45만 명이 찾았다 — 역대 최다")

    def test_prize_needs_a_named_winner(self):
        nameless = story(["‘올해의 작가상 2026’ 최종 수상자 발표"], ["o1", "o2", "o3"])
        self.assertEqual(buzz.rank([nameless], PERSON, [], "2026-11-01"), [])
        named = story(["국립현대미술관 ‘올해의 작가상’에 홍진훤"], ["o1", "o2", "o3"], names=[("홍진훤", "p_hong")])
        x = buzz.rank([named], PERSON, ["국립현대미술관"], "2026-11-01")[0]
        self.assertEqual(buzz.compose(x["a"], 3)["title"], "홍진훤, 국립현대미술관 ‘올해의 작가상’ 품었다")

    def test_non_art_crowd_is_ignored(self):
        st = story(["'호크·화랑·불검' 보은 달궜다, 소힘겨루기 2만명 흥행"], ["o1", "o2"])
        self.assertEqual(buzz.rank([st], PERSON, [], "2026-11-01"), [])

    def test_one_outlet_regional_first_is_not_enough(self):
        st = story(["라미 개인전 '빛으로 돌아가는 길' 대구 첫 개인전"], ["o1"])
        self.assertEqual(buzz.rank([st], PERSON, [], "2026-11-01"), [])

    def test_subject_merges_across_clusters(self):
        a = story(["린 허쉬만 리슨 아시아 첫 미술관 개인전"], ["o1"])
        b = story(["서울시립미술관, 린 허쉬만 리슨 개인전 개막"], ["o2", "o3"])
        x = buzz.rank([a, b], PERSON, ["서울시립미술관"], "2026-11-01")[0]
        self.assertEqual(x["outlets"], 3)
        self.assertEqual(x["a"]["name"], "린 허쉬만 리슨")


if __name__ == "__main__":
    unittest.main()

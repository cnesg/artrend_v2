import unittest

from artrend_mag import news_digest as nd


def art(i, title, publisher, day="2026-10-29", lang="ko", source="kr_naver_news_api", kind="news"):
    return dict(article_id=str(i), title=title, publisher=publisher, published_at=f"{day}T09:00:00+09:00", lang=lang,
                source_id=source, article_type=kind, categories="", canonical_url=f"https://x.test/{i}")


class StoryTests(unittest.TestCase):
    def test_same_story_from_several_outlets_is_one_story_and_outranks_single_items(self):
        rows = [art(1, "국립현대미술관 '올해의 작가상 2026' 홍진훤 선정", "a.kr"),
                art(2, "국립현대미술관 올해의 작가상 2026에 홍진훤 선정", "b.kr"),
                art(3, "국립현대미술관, '올해의 작가상 2026' 홍진훤 선정", "c.kr"),
                art(4, "구청 어린이 미술 체험 교실 모집", "d.kr")]
        stories = nd.build_stories(rows, lambda a: False, None, "2026-10-29")
        self.assertEqual(len(stories), 2)
        top = stories[0]
        self.assertEqual(len(top["members"]), 3)
        self.assertEqual(top["outlets"], ["a.kr", "b.kr", "c.kr"])
        self.assertIn("3개 매체 보도", top["reasons"])
        self.assertIn("수상·선정", top["reasons"])
        self.assertEqual(top["topic"], "people")
        self.assertIn("보도자료성(−1)", stories[1]["reasons"])

    def test_languages_never_merge_and_unrelated_titles_stay_apart(self):
        rows = [art(1, "Monet Water Lilies sells for record $80 million at Sotheby's", "x", lang="en"),
                art(2, "Monet Water Lilies sold for record $80 million at Sotheby's", "y", lang="en"),
                art(3, "Museum union strikes over layoffs", "z", lang="en")]
        stories = nd.build_stories(rows, lambda a: True, None, "2026-10-28")
        self.assertEqual(sorted(len(s["members"]) for s in stories), [1, 2])
        top = stories[0]
        self.assertEqual(top["topic"], "market")
        self.assertIn("가격·경매 결과", top["reasons"])
        self.assertIn("기록", top["reasons"])
        self.assertNotIn("당일 기사", top["reasons"])

    def test_name_matcher_needs_whole_latin_words_and_long_enough_cjk(self):
        m = nd.NameMatcher({"Rijksmuseum": "e1", "Tate Modern": "e2", "서울시립미술관": "e3", "이립": "e4", "Arts": "e5"})
        self.assertEqual(m.find("De Kooning at the Rijksmuseum"), [("Rijksmuseum", "e1")])
        self.assertEqual(m.find("Rijksmuseumplein party"), [])
        self.assertEqual(m.find("서울시립미술관 신임 관장에 이립 씨"), [("서울시립미술관", "e3")])
        self.assertEqual(m.find("Arts news"), [])

    def test_topics_cover_french_and_japanese(self):
        self.assertEqual(nd.topic_of(art(1, "L’Autrichien Josef Hofer est mort", "lm", lang="fr"))[0], "people")
        self.assertEqual(nd.topic_of(art(1, "Une expo inédite à Gand", "lm", lang="fr"))[0], "exhibition")
        self.assertEqual(nd.topic_of(art(1, "東京国立近代美術館で回顧展", "a", lang="ja"))[0], "exhibition")
        self.assertEqual(nd.topic_of(art(1, "Any title", "a", kind="review"))[0], "criticism")
        self.assertEqual(nd.topic_of(art(1, "날씨가 춥다", "a"))[0], "other")


if __name__ == "__main__":
    unittest.main()

import unittest

from artrend_mag import frontpage as fp


class TopicTests(unittest.TestCase):
    def test_photo_and_video_captions_are_not_art_topics(self):
        self.assertNotIn("사진", fp.topics_of("(사진) 구청장, 어르신 위문"))
        self.assertNotIn("미디어·영상", fp.topics_of("미디어 그룹, 영상 공개"))
        self.assertIn("사진", fp.topics_of("한영수 사진전 개막"))
        self.assertIn("미디어·영상", fp.topics_of("서서울미술관 뉴미디어 신진작가전"))
        self.assertIn("섬유·텍스타일", fp.topics_of("Textile works at Tate"))

    def test_luxury_auctions_are_flagged(self):
        self.assertTrue(fp.LUXURY.search("'더 맥캘란 1926', 경매서 38억에 낙찰… 위스키 역대 두 번째"))
        self.assertIsNone(fp.LUXURY.search("모네의 '붓꽃' 742억에 낙찰"))

    def test_article_time_without_clock_is_noon_kst(self):
        self.assertEqual(fp.ts("2026-10-29").isoformat(), "2026-10-29T12:00:00+09:00")
        self.assertEqual(fp.ts("2026-10-28T23:30:00+00:00").astimezone(fp.KST).date().isoformat(), "2026-10-29")
        self.assertIsNone(fp.ts("2026"))


if __name__ == "__main__":
    unittest.main()

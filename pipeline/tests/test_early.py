import unittest

from artrend_mag.early import is_after_the_fact, title_keys


class AfterTheFactTest(unittest.TestCase):
    def test_closing_tallies_are_retrospective(self):
        for t in ["'2026 경기도자비엔날레' 45일간 32만4천여명 찾아", "경기도자비엔날레, 45일간 대장정 마무리…32만4000여 명 관람",
                  "부산비엔날레 폐막", "Frieze London closes with record attendance"]:
            self.assertTrue(is_after_the_fact(t), t)

    def test_open_or_upcoming_news_is_not(self):
        for t in ["티에스터 게이츠, 한국 첫 개인전", "찾아가는 미술관 개막", "서서울미술관 신진작가전 11월 5일 개막"]:
            self.assertFalse(is_after_the_fact(t), t)

    def test_title_keys_strip_brackets(self):
        self.assertTrue(title_keys("《김희천: 두더지들》"))


if __name__ == "__main__":
    unittest.main()

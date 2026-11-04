from __future__ import annotations

import unittest

from artrend_mag.sources import sourcebook_am


# Minimal captures of the live listing-card markup observed on 2026-10-28.
ARTADIA_CARD = """
<li class="grid-item is-loaded">
  <a class="blank-link display-inline-block" href="https://artadia.org/artist/darrel-morris/">
    <div class="font-medium">Darrel Morris</div>
  </a>
  <div class="font-caption">
    <a href="https://artadia.org/award-year/2002/" rel="tag">2002</a>
    <a href="https://artadia.org/award-city/chicago/" rel="tag">Chicago</a>
  </div>
</li>
"""

BOMB_INTERVIEW_CARD = """
<div class="grid grid-cols-1 md:grid-cols-2 gap-8">
  <div>
    <h3 class="text-black text-xl font-bold mb-1">
      <a href="https://bombmagazine.org/articles/2026/10/20/emeline-atwood-by-tara-anne-dalbow/">
        <p>Emeline Atwood by Tara Anne Dalbow</p>
      </a>
    </h3>
    <div class="text-xl md:text-[22px] md:leading-[32px]">
      <p>A debut novel about complicated love and its wild, physical, animal edges.</p>
    </div>
  </div>
</div>
"""

JACK_SHAINMAN_CARD = """
<main>
  <div class="artist_link_container">
    <a class="small_font_size artist_link" href="/artists/nina_chanel_abney">
      <div class="artist_name">Nina Chanel Abney</div>
      <figure class="artist_image_container"></figure>
    </a>
  </div>
</main>
"""


class SourcebookAmericasParserTests(unittest.TestCase):
    def test_artadia_awardee_markup_preserves_year_and_city_taxonomies(self):
        rows = sourcebook_am._artadia_awardees(ARTADIA_CARD, "https://artadia.org/artist/")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Darrel Morris")
        self.assertEqual(rows[0]["year"], "2002")
        self.assertEqual(rows[0]["city"], "Chicago")
        self.assertEqual(rows[0]["city_slug"], "chicago")

    def test_bomb_listing_extracts_metadata_without_the_teaser_excerpt(self):
        rows = sourcebook_am._bomb_articles(BOMB_INTERVIEW_CARD, "https://bombmagazine.org/interview/")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Emeline Atwood by Tara Anne Dalbow")
        self.assertEqual(rows[0]["url"], "https://bombmagazine.org/articles/2026/10/20/emeline-atwood-by-tara-anne-dalbow")
        self.assertEqual(rows[0]["published_at"], "2026-10-20")
        self.assertEqual(rows[0]["author"], "Tara Anne Dalbow")
        self.assertNotIn("excerpt", rows[0])

    def test_jack_shainman_artist_directory_is_a_listed_artist_roster(self):
        rows = sourcebook_am._jack_artist_roster(JACK_SHAINMAN_CARD, "https://jackshainman.com/artists")

        self.assertEqual(rows, [{
            "name": "Nina Chanel Abney",
            "slug": "nina_chanel_abney",
            "url": "https://jackshainman.com/artists/nina_chanel_abney",
        }])


if __name__ == "__main__":
    unittest.main()

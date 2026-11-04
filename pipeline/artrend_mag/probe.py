"""One-shot access probe for candidate sources: robots.txt + a single GET of the entry URL.

Records what was actually observed (HTTP status, content type, size, feed links, JSON-LD, Next.js data,
visible text size). It does not collect records. Output: work/audit/probe_<stamp>.json
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup

from .config import AUDIT_ROOT, now_kst
from .http import Blocked, Fetcher, FetchError

CANDIDATES = [
    # (candidate_id, region, kind, url)
    ("KR-MMCA", "KR", "museum", "https://www.mmca.go.kr/exhibitions/progressList.do"),
    ("KR-SEMA", "KR", "museum", "https://sema.seoul.go.kr/kr/whatson/exhibition/list"),
    ("KR-LEEUM", "KR", "museum", "https://www.leeumhoam.org/leeum/exhibition"),
    ("KR-ARTSONJE", "KR", "museum", "https://artsonje.org/en/exhibition/"),
    ("KR-APMA", "KR", "museum", "https://apma.amorepacific.com/contents/exhibition/index.do"),
    ("KR-KUKJE", "KR", "gallery", "https://www.kukjegallery.com/exhibitions"),
    ("KR-GALLERYHYUNDAI", "KR", "gallery", "https://www.galleryhyundai.com/exhibition"),
    ("KR-ARARIO", "KR", "gallery", "https://www.arariogallery.com/exhibitions"),
    ("KR-PKM", "KR", "gallery", "https://www.pkmgallery.com/exhibitions"),
    ("KR-SONGEUN", "KR", "award", "https://www.songeun.or.kr/"),
    ("KR-DOOSAN", "KR", "award", "https://www.doosanartcenter.com/ko/exhibit/main"),
    ("KR-GWANGJU-BIENNALE", "KR", "biennial", "https://www.gwangjubiennale.org/gb/index.do"),
    ("KR-BUSAN-BIENNALE", "KR", "biennial", "https://www.busanbiennale.org/"),
    ("KR-KIAF", "KR", "fair", "https://kiaf.org/"),
    ("KR-FRIEZE-SEOUL", "KR", "fair", "https://www.frieze.com/fairs/frieze-seoul"),
    ("KR-MONTHLYART", "KR", "media", "https://monthlyart.com/"),
    ("KR-NEOLOOK", "KR", "media", "https://neolook.com/"),
    ("KR-DATAGOKR-MMCA", "KR", "api", "https://www.data.go.kr/data/15058313/openapi.do"),
    ("JP-MORI", "JP", "museum", "https://www.mori.art.museum/en/exhibitions/"),
    ("JP-MOT", "JP", "museum", "https://www.mot-art-museum.jp/en/exhibitions/"),
    ("JP-MOMAT", "JP", "museum", "https://www.momat.go.jp/en/exhibitions"),
    ("JP-NACT", "JP", "museum", "https://www.nact.jp/english/exhibitions/current.html"),
    ("JP-KANAZAWA21", "JP", "museum", "https://www.kanazawa21.jp/en/exhibition/"),
    ("JP-TOKAS", "JP", "residency", "https://www.tokyoartsandspace.jp/en/"),
    ("JP-TAKAISHII", "JP", "gallery", "https://www.takaishiigallery.com/en/exhibitions/"),
    ("JP-SCAI", "JP", "gallery", "https://www.scaithebathhouse.com/en/exhibitions/"),
    ("JP-TOMIOKOYAMA", "JP", "gallery", "https://tomiokoyamagallery.com/exhibitions/"),
    ("JP-ANOMALY", "JP", "gallery", "https://anomalytokyo.com/exhibition/"),
    ("JP-YOKOHAMA-TRI", "JP", "biennial", "https://www.yokohamatriennale.jp/"),
    ("JP-ARTFAIRTOKYO", "JP", "fair", "https://artfairtokyo.com/"),
    ("JP-APJ", "JP", "identifier", "https://artplatform.go.jp/"),
    ("JP-BIJUTSUTECHO", "JP", "media", "https://bijutsutecho.com/"),
    ("JP-TOKYOARTBEAT", "JP", "media", "https://www.tokyoartbeat.com/"),
    ("AM-AIC-API", "AMERICAS", "api", "https://api.artic.edu/api/v1/exhibitions?limit=1"),
    ("AM-MOMA", "AMERICAS", "museum", "https://www.moma.org/calendar/exhibitions"),
    ("AM-MOMA-GITHUB", "AMERICAS", "download", "https://github.com/MuseumofModernArt/collection"),
    ("AM-WHITNEY", "AMERICAS", "museum", "https://whitney.org/exhibitions"),
    ("AM-NEWMUSEUM", "AMERICAS", "museum", "https://www.newmuseum.org/exhibitions"),
    ("AM-GUGGENHEIM", "AMERICAS", "museum", "https://www.guggenheim.org/exhibitions"),
    ("AM-MASP", "AMERICAS", "museum", "https://masp.org.br/exposicoes"),
    ("AM-MUAC", "AMERICAS", "museum", "https://muac.unam.mx/exposiciones"),
    ("AM-NGC", "AMERICAS", "museum", "https://www.gallery.ca/whats-on/exhibitions-and-galleries"),
    ("AM-MALBA", "AMERICAS", "museum", "https://www.malba.org.ar/eventos/de/exposiciones/"),
    ("AM-PINACOTECA", "AMERICAS", "museum", "https://pinacoteca.org.br/programacao/exposicoes/"),
    ("AM-BIENAL-SP", "AMERICAS", "biennial", "https://bienal.org.br/"),
    ("AM-NADA", "AMERICAS", "fair", "https://www.newartdealers.org/"),
    ("AM-SFMOMA", "AMERICAS", "museum", "https://www.sfmoma.org/exhibitions/"),
    ("AM-HAMMER", "AMERICAS", "museum", "https://hammer.ucla.edu/exhibitions"),
    ("EU-TATE", "EUROPE", "museum", "https://www.tate.org.uk/whats-on"),
    ("EU-POMPIDOU", "EUROPE", "museum", "https://www.centrepompidou.fr/en/program/calendar"),
    ("EU-STEDELIJK", "EUROPE", "museum", "https://www.stedelijk.nl/en/exhibitions"),
    ("EU-REINASOFIA", "EUROPE", "museum", "https://www.museoreinasofia.es/en/exhibitions"),
    ("EU-SERPENTINE", "EUROPE", "museum", "https://www.serpentinegalleries.org/whats-on/"),
    ("EU-WHITECHAPEL", "EUROPE", "museum", "https://www.whitechapelgallery.org/exhibitions/"),
    ("EU-PALAISDETOKYO", "EUROPE", "museum", "https://palaisdetokyo.com/en/programme/"),
    ("EU-HAMBURGERBF", "EUROPE", "museum", "https://www.smb.museum/en/museums-institutions/hamburger-bahnhof/exhibitions/current/"),
    ("EU-MODERNAMUSEET", "EUROPE", "museum", "https://www.modernamuseet.se/stockholm/en/exhibitions/"),
    ("EU-MACBA", "EUROPE", "museum", "https://www.macba.cat/en/exhibitions-activities/exhibitions"),
    ("EU-MAXXI", "EUROPE", "museum", "https://www.maxxi.art/en/events/"),
    ("EU-MUSEUMSZTUKI", "EUROPE", "museum", "https://msl.org.pl/en/exhibitions"),
    ("EU-KUNSTHALLEWIEN", "EUROPE", "museum", "https://kunsthallewien.at/en/exhibitions/"),
    ("EU-LABIENNALE", "EUROPE", "biennial", "https://www.labiennale.org/en/art/2026"),
    ("EU-TURNER", "EUROPE", "award", "https://www.tate.org.uk/art/turner-prize"),
    ("EU-PINAULT", "EUROPE", "collection", "https://www.pinaultcollection.com/en"),
    ("GL-HAUSERWIRTH", "GLOBAL", "gallery", "https://www.hauserwirth.com/hauser-wirth-exhibitions/"),
    ("GL-ZWIRNER", "GLOBAL", "gallery", "https://www.davidzwirner.com/exhibitions"),
    ("GL-GAGOSIAN", "GLOBAL", "gallery", "https://gagosian.com/exhibitions/"),
    ("GL-WHITECUBE", "GLOBAL", "gallery", "https://www.whitecube.com/gallery-exhibitions"),
    ("EU-SADIECOLES", "EUROPE", "gallery", "https://www.sadiecoles.com/exhibitions"),
    ("EU-MENNOUR", "EUROPE", "gallery", "https://mennour.com/exhibitions"),
    ("GL-ARTBASEL", "GLOBAL", "fair", "https://www.artbasel.com/basel/exhibitors"),
    ("MED-EFLUX-RSS", "GLOBAL", "media", "https://www.e-flux.com/rss/"),
    ("MED-HYPERALLERGIC-RSS", "GLOBAL", "media", "https://hyperallergic.com/feed/"),
    ("MED-ARTNEWS-RSS", "GLOBAL", "media", "https://www.artnews.com/feed/"),
    ("MED-ARTFORUM", "GLOBAL", "media", "https://www.artforum.com/feed/"),
    ("MED-FRIEZE", "GLOBAL", "media", "https://www.frieze.com/"),
    ("MED-ARTREVIEW-RSS", "GLOBAL", "media", "https://artreview.com/feed/"),
    ("MED-TAN", "GLOBAL", "media", "https://www.theartnewspaper.com/rss.xml"),
    ("MED-ARTASIAPACIFIC", "GLOBAL", "media", "https://artasiapacific.com/"),
    ("MED-OCULA", "GLOBAL", "media", "https://ocula.com/magazine/"),
    ("MED-ARTINAMERICA-RSS", "GLOBAL", "media", "https://www.artnews.com/c/art-in-america/feed/"),
    ("ID-WIKIDATA", "GLOBAL", "identifier", "https://query.wikidata.org/sparql?query=SELECT%20%3Fx%20WHERE%20%7B%20BIND(1%20AS%20%3Fx)%20%7D&format=json"),
    ("ID-WIKIMEDIA-PV", "GLOBAL", "api", "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/Haegue_Yang/daily/20260901/20260930"),
    ("ID-GETTY", "GLOBAL", "identifier", "https://vocab.getty.edu/sparql"),
]


def probe_one(c):
    cid, reg, kind, url = c
    stats: dict = {}
    f = Fetcher(f"probe_{cid}", "probe", False, stats, max_requests=3)
    out = {"candidate_id": cid, "region": reg, "kind": kind, "url": url}
    try:
        out["robots"] = f.robots_state(url)
        out["robots_allows_entry"] = f.allowed(url)
        r = f.get(url, conditional=False, store=False)
        html = r.text
        out.update(status=r.status, final_url=r.final_url, content_type=r.content_type, bytes=len(r.content))
        if "html" in r.content_type:
            soup = BeautifulSoup(html, "lxml")
            out["title"] = (soup.title.get_text(strip=True) if soup.title else "")[:120]
            out["feeds"] = [a.get("href") for a in soup.find_all("link", type=re.compile("rss|atom"))][:5]
            out["jsonld_blocks"] = len(soup.find_all("script", type="application/ld+json"))
            out["jsonld_event_mentions"] = sum(s.get_text().count('"Event"') + s.get_text().count('ExhibitionEvent') for s in soup.find_all("script", type="application/ld+json"))
            out["next_data"] = bool(soup.find("script", id="__NEXT_DATA__"))
            out["nuxt"] = "__NUXT__" in html
            for s in soup(["script", "style", "noscript"]):
                s.decompose()
            out["visible_text_chars"] = len(soup.get_text(" ", strip=True))
            out["anchors"] = len(soup.find_all("a"))
        elif "xml" in r.content_type or "rss" in r.content_type:
            out["feed_items"] = html.count("<item") + html.count("<entry")
        elif "json" in r.content_type:
            out["json_head"] = html[:200]
    except Blocked as b:
        out.update(blocked=b.kind, status=b.status, detail=b.detail)
    except FetchError as e:
        out.update(error=str(e)[:200])
    except Exception as e:
        out.update(error=f"{type(e).__name__}: {e}"[:200])
    return out


def main(ids=None):
    cands = [c for c in CANDIDATES if not ids or c[0] in ids]
    with ThreadPoolExecutor(max_workers=8) as ex:  # distinct hosts; per-host politeness is preserved
        res = list(ex.map(probe_one, cands))
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    p = AUDIT_ROOT / f"probe_{now_kst().strftime('%Y%m%dT%H%M%S')}.json"
    p.write_text(json.dumps({"probed_at": now_kst().isoformat(), "results": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(p)
    for r in res:
        print(r["candidate_id"], r.get("status"), r.get("blocked") or r.get("error") or "", r.get("robots"),
              r.get("robots_allows_entry"), r.get("bytes"), r.get("visible_text_chars"), r.get("feeds") or "", r.get("feed_items") or "",
              "NEXT" if r.get("next_data") else "", f"ld={r.get('jsonld_blocks')}" if r.get("jsonld_blocks") else "")


if __name__ == "__main__":
    main(sys.argv[1:])

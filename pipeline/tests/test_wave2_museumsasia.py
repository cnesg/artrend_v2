from __future__ import annotations

import hashlib
import sqlite3
import unittest

from artrend_mag import db, runner
from artrend_mag.sources import wave2_museumsasia as w


class FakeResponse:
    def __init__(self, url, text):
        self.url = url
        self.final_url = url
        self.status = 200
        self.text = text
        self.content = text.encode("utf-8")
        self.fetched_at = "2026-10-28T14:00:00+09:00"
        self.sha256 = hashlib.sha256(self.content).hexdigest()
        self.raw_path = None


class FakeContext:
    mode = "incremental"
    parser_version = w.PARSER_VERSION

    def __init__(self, con, source_id, pages):
        self.con, self.source_id, self.pages = con, source_id, pages
        self.meta = next(r for r in w.SOURCES if r["source_id"] == source_id)
        self.stats, self.notes, self.calls = {}, [], []

    def fetch(self, url, params=None, **kw):
        full = url if not params else url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        self.calls.append(full)
        if full not in self.pages:
            raise AssertionError(f"unexpected fetch {full}")
        return FakeResponse(full, self.pages[full])

    def evidence(self, response, locator=None, excerpt=None):
        return db.add_evidence(self.con, source_id=self.source_id, url=response.url, fetched_at=response.fetched_at,
                               http_status=200, raw_path=None, raw_sha256=response.sha256, locator=locator,
                               excerpt=excerpt, parser_version=self.parser_version)

    def note(self, message):
        self.notes.append(message)

    def count(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n


def _con(source_id):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    db.init_schema(con)
    row = next(r for r in w.SOURCES if r["source_id"] == source_id)
    db.upsert_source(con, source_id, **{k: v for k, v in row.items() if k in db.SOURCE_FIELDS + db.STATUS_FIELDS})
    con.commit()
    return con


NMWA_CURRENT = """<ul class="nmwa-exhibition-special-list"><li class="nmwa-exhibition-item" data-nmwa-exhibition-item>
<div class="nmwa-exhibition-special-card"><span class="nmwa-ui-thumb"><img class="nmwa-exhibition-special-image" src="https://www.nmwa.go.jp/wp-content/uploads/2026/09/2026turner.jpg.nmwa.webp" alt=""></span>
<div class="nmwa-exhibition-special-body"><div class="nmwa-ui-badges"><span class="nmwa-ui-badge is-now">開催中</span><span class="nmwa-ui-badge is-category">企画展</span></div>
<p class="nmwa-ui-card-title nmwa-exhibition-special-title">テート美術館　ターナー展――崇高の絵画、現代美術との対話</p>
<p class="nmwa-ui-card-term nmwa-exhibition-special-term">2026年10月24日[土]－2027年2月21日[日]</p>
<a class="nmwa-ui-button nmwa-exhibition-special-detail" href="https://www.nmwa.go.jp/jp/exhibitions/2026turner.html">詳細へ</a>
<a class="nmwa-ui-more nmwa-exhibition-ticket" href="https://turner2026-27.exhibit.jp/ticket/index.html">チケット案内</a></div></div></li></ul>
<ul class="splide__list"><li class="splide__slide" data-nmwa-exhibition-item><a class="nmwa-ui-card" href="https://www.nmwa.go.jp/jp/exhibitions/2026cinf.html">
<span class="nmwa-ui-badges"><span class="nmwa-ui-badge is-now">開催中</span><span class="nmwa-ui-badge is-category">常設展</span></span>
<span class="nmwa-ui-card-title">コレクション・イン・フォーカス</span><span class="nmwa-ui-card-term">2026年3月28日[土]― 2027年1月中旬予定</span></a></li></ul>"""
NMWA_UPCOMING = """<ul class="nmwa-exhibition-special-list"><li class="nmwa-exhibition-item" data-nmwa-exhibition-item><div class="nmwa-exhibition-special-card">
<div class="nmwa-exhibition-special-body"><div class="nmwa-ui-badges"><span class="nmwa-ui-badge is-next">開催予定</span><span class="nmwa-ui-badge is-category">企画展</span></div>
<p class="nmwa-ui-card-title">マティス 黒と白の詩学</p><p class="nmwa-ui-card-sub nmwa-exhibition-special-sub">—ピエール＆タナ・マティス財団の版画コレクションを中心に</p>
<p class="nmwa-ui-card-term">2027年3月20日[土]－7月19日[月・祝]</p><a class="nmwa-ui-button" href="https://www.nmwa.go.jp/jp/exhibitions/2027matisse.html">詳細へ</a></div></div></li></ul>"""
NMWA_PAST = """<section class="nmwa-exhibition-year" data-nmwa-year="2020"><ul class="nmwa-exhibition-rows">
<li class="nmwa-exhibition-rows-item" data-nmwa-row-card><a class="nmwa-exhibition-row" href="/jp/exhibitions/2020manuscript3.html">
<span class="nmwa-exhibition-row-body"><span class="nmwa-ui-badges"><span class="nmwa-ui-badge is-category">小企画展</span></span>
<span class="nmwa-ui-card-title">内藤コレクション展III「写本彩飾の精華 天に捧ぐ歌、神の理」</span><span class="nmwa-ui-card-term">2020年9月8日（火）～2020年10月18日（日）</span></span></a></li></ul></section>
<section class="nmwa-exhibition-year" data-nmwa-year="2025"><ul class="nmwa-exhibition-rows">
<li class="nmwa-exhibition-rows-item" data-nmwa-row-card><a class="nmwa-exhibition-row" href="/jp/exhibitions/2025dokomiru.html">
<span class="nmwa-exhibition-row-body"><span class="nmwa-ui-badges"><span class="nmwa-ui-badge is-category">企画展</span></span>
<span class="nmwa-ui-card-title">西洋絵画、どこから見るか？―ルネサンスから印象派まで</span><span class="nmwa-ui-card-sub">サンディエゴ美術館 vs 国立西洋美術館</span>
<span class="nmwa-ui-card-term">2025年3月11日[火]－6月8日[日]</span></span></a></li></ul></section>"""

MOMAK_CURRENT = """<main id="scExhibition" class="list"><h2>開催中<hr></h2><section class="layout-2col-01"><div><img src="https://www.momak.go.jp/wp-content/uploads/2026/09/banner.jpg"></div><div>
<h3>ジュエリーは、誰を夢みる</h3><em>2026.10.24 sat. - 01.17 sun.</em><p class="line-3">本文</p><a href="https://www.momak.go.jp/Japanese/?p=130297" class="btn-default">Read More</a></div></section>
<h2 id="next">これからの展覧会<hr></h2><section class="layout-01"><div><h3>現在開催予定の展覧会はありません。</h3></div></section></main>"""
MOMAK_DETAIL = """<link rel="canonical" href="https://www.momak.go.jp/Japanese/exhibitionarchive/2026/468.html" />
<main><dl><dt>会期</dt><dd>2026年10月24日（土）～2027年1月17日（日）</dd></dl><p>開館時間 午前10時～午後6時</p></main>"""
MOMAK_YEAR = """<div class="content"><section><a href="https://www.momak.go.jp/Japanese/event/467"><img src="x.jpg" alt=""></a><span class="no">No.467</span>
<span class="name"><a href="https://www.momak.go.jp/Japanese/event/467"><span style="color: gray;">日本イタリア国交樹立 160 周年記念・フォンタネージ来日 150 周年記念</span><br>フォンタネージ—イタリアの光・心の風景</a></span>
<span class="date">2026年7月18日(土)～10月4日(日)</span></section>
<section><a href="https://www.momak.go.jp/Japanese/event/466"><img src="y.jpg" alt=""></a><span class="no">No.466</span><span class="name"><a href="https://www.momak.go.jp/Japanese/event/466">モダン都市生活と竹久夢二―川西英コレクション</a></span>
<span class="date">2026年3月28日(土)～6月21日(日)</span></section></div>"""
MOMAK_CG_PAST = """<div class="col-3 list-type-01"><h2>コレクション展<hr></h2><p><a href="https://www.momak.go.jp/Japanese/event/2026%e5%b9%b4%e5%ba%a6-%e7%ac%ac2%e5%9b%9e">2026年度 第2回コレクション展</a><span class="period">2026年7月18日(土)～10月4日(日)</span></p></div>"""

NMAO_CURRENT = """<div id="ex_posters" class="columns"><div class="ex_poster column3"><div class="imgs"><a href="x"><img src="a.jpg"></a></div><div class="txts"><div class="meta"><div class="status on">開催中</div><div class="floor">展覧会</div></div>
<h2><a href="https://www.nmao.go.jp/events/event/20261010_nmao-satellite/"><span style="font-size: 0.8em;">国立国際美術館(NMAO)×大阪中之島美術館(NAKKA)コレクション活用連携事業</span><br />コレナカ NMAOサテライト</a></h2>
<p>2026年10月10日（土）&ndash; 2026年11月7日（土）</p><p class="pt5">会場：大阪中之島美術館</p> </div></div>
<div class="ex_poster column3"><div class="txts"><div class="meta"><div class="status">開催予定</div><div class="floor">特別展</div></div>
<h2><a href="https://www.nmao.go.jp/events/event/20261201_stratified-languages/">コトバの重なる場所</a></h2><p>2026年12月1日（火）&ndash; 2027年3月14日（日）</p></div></div></div>"""
NMAO_PAST = """<table class="extbl"><tbody><tr><td><a href="https://www.nmao.go.jp/events/event/20260314_nakanishi/">中西夏之 緩やかにみつめるためにいつまでも佇む、装置</a></td>
<td>2026年3月14日（土）&ndash; 2026年6月14日（日）</td></tr><tr><td><a href="https://www.nmao.go.jp/events/event/old1/">古い展覧会</a></td><td>2019年4月1日（月）&ndash; 2019年5月6日（月）</td></tr></tbody></table>"""

YOKOBI_NOW = """<div class="exhibitionMain__set"><figure><a href="https://yokohama.art.museum/exhibition/202607_mohriyuko/"><img src="https://yokohama.art.museum/wp-content/uploads/2026/06/x.jpg"></a></figure>
<div class="txtBox"><div class="txtBox__info"><p>無料</p></div><h3><a href="https://yokohama.art.museum/exhibition/202607_mohriyuko/">毛利悠子　Recompose<br />
第60回ヴェネチア・ビエンナーレ日本館帰国展</a></h3><p class="dateTxt">
2026年7月24日（金）
- 2026年11月23日（月）
</p></div></div>"""
YOKOBI_PAST = """<div class="exhibitionSub__set"><div class="txtBox"><div class="txtBox__copy"><span class="label kikaku">企画展</span>
<h3 class=""><a href="https://yokohama.art.museum/exhibition/202604_imamurashiko/">没後110年<br />
日本画の革命児　今村紫紅</a></h3><p class="dateTxt">
2026年4月25日（土）
- 2026年6月28日（日）
</p></div></div></div>
<div class="exhibitionSub__set"><div class="txtBox"><div class="txtBox__copy"><span class="label collection">コレクション展</span>
<h3 class=""><a href="https://yokohama.art.museum/exhibition/202604_collection/">コレクション展<br />
2026年4月25日（土）－6月28日（日）</a></h3><p class="dateTxt">
2026年4月25日（土）
- 2026年6月28日（日）
</p></div></div></div>"""

BENESSE = """<div class="right news-ind gl-linkdeco"><h3>2026年</h3><dl class="entry-list"><dt><span class="news-ind-day">2026年10月13日</span>
<span class="news-ind-category"><span class="gl-category c-naoshima2 label-teshima">豊島</span><span class="gl-category c-stay label-information">お知らせ</span></span></dt>
<dd><a href="/news/20261013-3638.html">夕暮れの針工場｜2026年11月・12月</a></dd></dl></div>"""

BUSAN_NOW = """<div class="listTypeG"><ul><li><div class="thumb_img"><a href="/tblTsite07Display/viewNowClient.nm?id=20260913112010274"><img src="/images/custdisplay/a.png"></a></div>
<div class="infor"><span class="tit"><a href="/tblTsite07Display/viewNowClient.nm?id=20260913112010274">그러나 우리는 아직도 이 바다 높은 물결 위에 있다 Still We are Borne on These Waves:1945-1953</a></span>
<span class="date">2026-09-17 – 2027-02-14</span></div></li></ul></div>"""
BUSAN_PAST = """<div class="listTypeC"><ul><li><a href="#" name="btnHqpicView" attr-kval="id=20260921142919611"><div class="thumb_img"><img src="/images/custdisplay/p.png" alt="x"></div>
<div class="infor"><span class="tit">젊은 시각 새로운 시선 해외전 </span><span class="date">2026-08-23 – 2026-10-07</span></div></a></li>
<li><a href="#" name="btnHqpicView" attr-kval="id=20230101000000001"><div class="infor"><span class="tit">BMA 상시</span><span class="date">2023-01-01 – 2099-12-31</span></div></a></li></ul></div>"""
BUSAN_DETAIL_PAST = """<div class="viewTypeD"><div class="exh_img"><div class="infor"><h2>젊은 시각 새로운 시선 해외전 </h2><span class="date">2026-08-23 – 2026-10-07</span></div></div>
<div class="exh_box"><div class="infor"><dl><dt>전시부문</dt><dd>해외</dd><dt>작품수</dt><dd>60</dd><dt>전시장소</dt><dd>중국 금일미술관 </dd><dt>전시문의</dt><dd>051-740-4268</dd></dl></div></div></div>"""

DAEGU = """<div class="c_exh_lst"><div class="inr"><div class="item"><a href="javascript:fnView('EHI_00000342');"><span class="img"><span class="inr"><img src='/icms/file/getImage.do?atchFileId=F&fileSn=0'/></span></span>
<span class="step coming">예정전시</span><span class="item_tit">
 제26회 이인성미술상 수상자전 《이명미: 더 이상은 말할 수 없다》
 </span><span class="info_area"><span class="info"><em class="info_tit">기간</em><span class="info_date">2026-11-03~2027-02-14</span></span>
<span class="info"><em class="info_tit">장소</em><span>대구미술관 2,3전시실, 선큰가든</span></span></span></a></div></div></div>"""

GMOMA_LIST = """<ul class="eee-tab-wrap tab-wrap"><li><a href="https://gmoma.ggcf.kr/exhibitions?progress=now" class="on">현재 / 예정</a></li></ul>
<ul><li class="item-list"><div><a href="/exhibitions/207"><div class="img-box"><img src="/storage/upload/2026/08/27/j.jpg" alt=""></div><p>《다시 볼래? RE:VIEW》</p>
<p class="date">
 2026. 09. 01. — 2026. 11. 29.
 </p></a></div><div><a href="/exhibitions/49"><p>경기도미술관 상설전시 《멈춰서서》</p><p class="date">
 2023. 09. 15. —
 </p></a></div></li></ul>"""
GMOMA_DETAIL = """<div class="event-shcema" vocab="https://schema.org/" typeof="exhibitionEvent"><meta property="resource" content="https://gmoma.ggcf.kr/exhibitions/207">
<meta property="location" content="B1 경기도미술관"><meta property="name" content="《다시 볼래? RE:VIEW》"><meta property="startDate" datetime="2026-09-01" content="2026-09-01">
<meta property="endDate" datetime="2026-11-29" content="2026-11-29"><meta property="director" content="최혜경 학예연구사"></div>
<div class="view-content-area"><div class="view-title"><h3>2026 경기도미술관 x 국립현대미술관 미술은행 소장품전</h3><h2>《다시 볼래? RE:VIEW》</h2><h4>2026. 09. 01. ~ 2026. 11. 29.<br>경기도미술관</h4></div>
<div class="section-03"><dl class="meta"><dt>장소</dt><dd>경기도미술관</dd><dt>참여작가</dt><dd>배형경, 양태근, 최정화</dd><dt>기획</dt><dd>최혜경 학예연구사</dd>
<dt>주최·주관</dt><dd>경기도미술관, 국립현대미술관 미술은행</dd></dl></div></div>"""
GMOMA_DETAIL_OPEN = """<div class="event-shcema"><meta property="name" content="경기도미술관 상설전시 《멈춰서서》"><meta property="startDate" datetime="2023-09-15" content="2023-09-15"></div>
<div class="view-content-area"><div class="view-title"><h3></h3><h2>경기도미술관 상설전시 《멈춰서서》</h2></div><div class="section-03"><dl class="meta"><dt>장소</dt><dd>야외 전시장 및 미술관 벽면</dd>
<dt>참여작가</dt><dd>강신영, 미쉘 뒤포르</dd><dt>기획</dt><dd>경기도미술관</dd></dl></div></div>"""

NJP_LIST = """<div class="section"><ul class="list"><li><a href=/exhibitions/244><div class="thumb" style="background-image: url('/storage/upload/2026/06/19/8t.jpg');"></div></a>
<div class="meta-info"><a href="https://njp.ggcf.kr/exhibitions?tag=%EC%A0%84%EC%8B%9C" class="category">전시</a><a href="/exhibitions/244" class="title">별, 괘卦</a>
<div class="date">2026. 7. 16.—2027. 2. 14.</div></div></li></ul></div>"""
NJP_DETAIL = """<div class="exhibition-show"><div class="exhibition-grid section"><div class="meta-info"><div class="category">전시</div><div class="title">별, 괘卦</div>
<div class="date">2026. 7. 16.—2027. 2. 14.</div><div class="details"><p><strong>제1회 백남준미디어아트페스티벌</strong></p><dl class="meta"><dt>장소</dt><dd>백남준아트센터 제1전시실</dd>
<dt>일시</dt><dd>
 2026. 7. 16.—2027. 2. 14.
 </dd><dt>기획</dt><dd>강연섭</dd><dt>참여작가</dt><dd>백남준</dd><dt>주최주관</dt><dd>경기문화재단, 백남준아트센터</dd></dl></div></div></div></div>"""
NJP_DETAIL_ELSEWHERE = NJP_DETAIL.replace("백남준아트센터 제1전시실", "용인포은아트홀 야외마당")


class ParserTests(unittest.TestCase):
    def test_range_precision_and_year_rollover(self):
        self.assertEqual(w.parse_range("2026年10月24日[土]－2027年2月21日[日]"), ("2026-10-24", "day", "2027-02-21", "day"))
        self.assertEqual(w.parse_range("2025年12月20日(土)～3月8日(日)"), ("2025-12-20", "day", "2026-03-08", "day"))
        self.assertEqual(w.parse_range("2026年3月28日[土]― 2027年1月中旬予定"), ("2026-03-28", "day", "2027-01", "month"))
        self.assertEqual(w.parse_range("2026. 7. 23.—2026. 11. 11."), ("2026-07-23", "day", "2026-11-11", "day"))
        self.assertEqual(w.parse_range("2023. 09. 15. — "), ("2023-09-15", "day", None, None))
        self.assertEqual(w.parse_range("2023-01-01 – 2099-12-31"), ("2023-01-01", "day", None, None))
        self.assertEqual(w.parse_range("2022年10⽉" + "22⽇（⼻）– 2023年1⽉" + "9⽇")[:3], ("2022-10-22", "day", "2023-01-09"))
        self.assertEqual(w.parse_range("2026年8月1日（土） - 2026年11月23日（月）"), ("2026-08-01", "day", "2026-11-23", "day"))

    def test_nmwa_cards_keep_japanese_and_flag_upcoming(self):
        cur = w.parse_nmwa(NMWA_CURRENT, w.NMWA)
        self.assertEqual([c["key"] for c in cur], ["2026turner", "2026cinf"])
        self.assertEqual(cur[0]["title"], "テート美術館　ターナー展――崇高の絵画、現代美術との対話".replace("　", " "))
        self.assertEqual(cur[0]["category"], "企画展")
        up = w.parse_nmwa(NMWA_UPCOMING, w.NMWA)[0]
        self.assertTrue(up["upcoming"])
        self.assertEqual(up["sub"], "—ピエール＆タナ・マティス財団の版画コレクションを中心に")
        past = w.parse_nmwa(NMWA_PAST, w.NMWA)
        self.assertEqual(past[1]["url"], "https://www.nmwa.go.jp/jp/exhibitions/2025dokomiru.html")
        self.assertEqual(past[1]["sub"], "サンディエゴ美術館 vs 国立西洋美術館")

    def test_momak_current_detail_year_and_collection_lists(self):
        cur = w.parse_momak_current(MOMAK_CURRENT, w.MOMAK)
        self.assertEqual(len(cur), 1)
        self.assertEqual(cur[0]["title"], "ジュエリーは、誰を夢みる")
        detail = w.parse_momak_detail(MOMAK_DETAIL)
        self.assertEqual(detail["number"], "468")
        self.assertEqual(w.parse_range(detail["date_text"]), ("2026-10-24", "day", "2027-01-17", "day"))
        year = w.parse_momak_year(MOMAK_YEAR, w.MOMAK)
        self.assertEqual(year[0]["key"], "no-467")
        self.assertEqual(year[0]["title"], "フォンタネージ—イタリアの光・心の風景")
        self.assertTrue(year[0]["prefix"].startswith("日本イタリア国交樹立"))
        self.assertIsNone(year[1]["prefix"])
        past = w.parse_momak_collection_past(MOMAK_CG_PAST, w.MOMAK)
        self.assertEqual(past[0]["date_text"], "2026年7月18日(土)～10月4日(日)")

    def test_nmao_prefix_venue_and_past_table(self):
        cur = w.parse_nmao_current(NMAO_CURRENT, w.NMAO)
        self.assertEqual(cur[0]["title"], "コレナカ NMAOサテライト")
        self.assertEqual(cur[0]["venue"], "大阪中之島美術館")
        self.assertFalse(cur[0]["upcoming"])
        self.assertTrue(cur[1]["upcoming"])
        past = w.parse_nmao_past(NMAO_PAST, w.NMAO)
        self.assertEqual([p["key"] for p in past], ["20260314_nakanishi", "old1"])

    def test_yokohama_titles_drop_embedded_date_lines(self):
        now = w.parse_yokobi_current(YOKOBI_NOW, w.YOKOBI)
        self.assertEqual(now[0]["title"], "毛利悠子 Recompose 第60回ヴェネチア・ビエンナーレ日本館帰国展")
        past = w.parse_yokobi_current(YOKOBI_PAST, w.YOKOBI)
        self.assertEqual(past[0]["label"], "企画展")
        self.assertEqual(past[1]["title"], "コレクション展")
        self.assertEqual(past[1]["date_text"], "2026年4月25日（土） - 2026年6月28日（日）")

    def test_benesse_news_index(self):
        item = w.parse_benesse_news(BENESSE, w.BENESSE)[0]
        self.assertEqual(item["published_at"], "2026-10-13")
        self.assertEqual(item["categories"], "豊島; お知らせ")
        self.assertEqual(item["url"], "https://benesse-artsite.jp/news/20261013-3638.html")

    def test_busan_lists_detail_and_country(self):
        now = w.parse_busan_list(BUSAN_NOW, w.BUSAN)[0]
        self.assertEqual(now["id"], "20260913112010274")
        past = w.parse_busan_list(BUSAN_PAST, w.BUSAN, past=True)
        self.assertEqual(past[0]["url"], "https://art.busan.go.kr/tblTsite07Display/viewPastClient.nm?id=20260921142919611")
        info = w.parse_busan_detail(BUSAN_DETAIL_PAST)
        self.assertEqual((info["section"], info["venue"]), ("해외", "중국 금일미술관"))
        self.assertEqual(w.busan_venue(info["section"], info["venue"]), (None, "CN"))
        self.assertEqual(w.busan_venue("국내", "미술관 본관 2층 전시실"), ("Busan", "KR"))
        self.assertEqual(w.busan_venue("국내", None), (None, None))

    def test_daegu_list_fields(self):
        item = w.parse_daegu_list(DAEGU)[0]
        self.assertEqual(item["id"], "EHI_00000342")
        self.assertEqual(item["status"], "예정전시")
        self.assertEqual(item["date_text"], "2026-11-03~2027-02-14")
        self.assertEqual(item["venue"], "대구미술관 2,3전시실, 선큰가든")

    def test_gyeonggi_cms_lists_and_details(self):
        cards = w.parse_ggcf_list(GMOMA_LIST, w.GMOMA)
        self.assertEqual([c["id"] for c in cards], ["207", "49"])
        self.assertEqual(cards[0]["title"], "《다시 볼래? RE:VIEW》")
        info = w.parse_gmoma_detail(GMOMA_DETAIL)
        self.assertEqual((info["start"], info["end"]), ("2026-09-01", "2026-11-29"))
        self.assertEqual(info["artists"], ["배형경", "양태근", "최정화"])
        self.assertEqual(info["curators"], ["최혜경 학예연구사"])
        self.assertEqual(w._person_name("최혜경 학예연구사"), "최혜경")
        open_ended = w.parse_gmoma_detail(GMOMA_DETAIL_OPEN)
        self.assertIsNone(open_ended["end"])
        njp = w.parse_njp_list(NJP_LIST, w.NJP)[0]
        self.assertEqual((njp["id"], njp["date_text"]), ("244", "2026. 7. 16.—2027. 2. 14."))
        detail = w.parse_njp_detail(NJP_DETAIL)
        self.assertEqual((detail["artists"], detail["curators"]), (["백남준"], ["강연섭"]))


class CollectTests(unittest.TestCase):
    def test_nmwa_collect_is_idempotent_and_filters_pre_2023(self):
        sid = "wave2_nmwa_exhibitions"
        pages = {f"{w.NMWA}/jp/exhibitions/current.html": NMWA_CURRENT, f"{w.NMWA}/jp/exhibitions/upcoming.html": NMWA_UPCOMING,
                 f"{w.NMWA}/jp/exhibitions/past/index.html": NMWA_PAST}
        con = _con(sid)
        ctx = FakeContext(con, sid, pages)
        ctx.mode = "initial"
        w.collect(ctx)
        rows = con.execute("SELECT source_event_key,title,subtype,start_date,end_date,end_precision,country_code,city,announced_status,title_lang "
                           "FROM events ORDER BY source_event_key").fetchall()
        self.assertEqual([r["source_event_key"] for r in rows], ["2025dokomiru", "2026cinf", "2026turner", "2027matisse"])
        cinf = next(r for r in rows if r["source_event_key"] == "2026cinf")
        self.assertEqual((cinf["subtype"], cinf["end_date"], cinf["end_precision"]), ("collection_display", "2027-01", "month"))
        matisse = next(r for r in rows if r["source_event_key"] == "2027matisse")
        self.assertEqual((matisse["announced_status"], matisse["country_code"], matisse["city"], matisse["title_lang"]),
                         ("scheduled", "JP", "Tokyo", "ja"))
        self.assertEqual(ctx.stats["parsed"], 4)
        again = FakeContext(con, sid, pages)
        again.mode = "initial"
        w.collect(again)
        self.assertEqual(again.stats.get("inserted", 0), 0)
        self.assertEqual(again.stats.get("unchanged"), 4)

    def test_busan_overseas_show_takes_actual_venue_country(self):
        sid = "wave2_busan_moa_exhibitions"
        pages = {f"{w.BUSAN}/tblTsite07Display/listNowClient.nm": BUSAN_NOW,
                 f"{w.BUSAN}/tblTsite07Display/listFutureClient.nm": "<div class='listTypeG'><ul></ul></div>",
                 f"{w.BUSAN}/tblTsite07Display/listPastClient.nm": BUSAN_PAST,
                 f"{w.BUSAN}/tblTsite07Display/listPastClient.nm?page_no=2": "<div class='listTypeC'><ul></ul></div>",
                 f"{w.BUSAN}/tblTsite07Display/viewPastClient.nm?id=20260921142919611": BUSAN_DETAIL_PAST,
                 f"{w.BUSAN}/tblTsite07Display/viewNowClient.nm?id=20260913112010274":
                     BUSAN_DETAIL_PAST.replace("해외", "국내").replace("중국 금일미술관", "미술관 본관 2층 전시실").replace("젊은 시각 새로운 시선 해외전", "그러나 우리는").replace("2026-08-23 – 2026-10-07", "2026-09-17 – 2027-02-14"),
                 f"{w.BUSAN}/tblTsite07Display/viewPastClient.nm?id=20230101000000001": BUSAN_DETAIL_PAST.replace("젊은 시각 새로운 시선 해외전", "BMA 상시").replace("2026-08-23 – 2026-10-07", "2023-01-01 – 2099-12-31")}
        con = _con(sid)
        ctx = FakeContext(con, sid, pages)
        ctx.mode = "initial"
        w.collect(ctx)
        by_key = {r["source_event_key"]: r for r in con.execute("SELECT * FROM events")}
        overseas = by_key["exhibition-20260921142919611"]
        self.assertEqual((overseas["country_code"], overseas["edition_region"]), ("CN", "OTHER"))
        self.assertEqual(overseas["title"], "젊은 시각 새로운 시선 해외전")
        sentinel = by_key["exhibition-20230101000000001"]
        self.assertEqual((sentinel["start_date"], sentinel["end_date"]), ("2023-01-01", None))
        self.assertEqual(by_key["exhibition-20260913112010274"]["country_code"], "KR")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM events WHERE country_code IS NULL").fetchone()[0], 0)

    def test_gmoma_collect_stores_artists_and_curators_without_institutions(self):
        sid = "wave2_gmoma_exhibitions"
        pages = {f"{w.GMOMA}/exhibitions?progress=now": GMOMA_LIST, f"{w.GMOMA}/exhibitions?progress=ago": "<ul></ul>",
                 f"{w.GMOMA}/exhibitions/207": GMOMA_DETAIL, f"{w.GMOMA}/exhibitions/49": GMOMA_DETAIL_OPEN}
        con = _con(sid)
        ctx = FakeContext(con, sid, pages)
        w.collect(ctx)
        events = {r["source_event_key"]: r for r in con.execute("SELECT * FROM events")}
        self.assertEqual(events["exhibition-207"]["end_date"], "2026-11-29")
        self.assertEqual((events["exhibition-49"]["start_date"], events["exhibition-49"]["end_date"]), ("2023-09-15", None))
        self.assertEqual(events["exhibition-207"]["country_code"], "KR")
        roles = con.execute("SELECT p.role, p.name_as_listed, p.extraction_method FROM event_participants p JOIN events e USING(event_id) "
                            "WHERE e.source_event_key='exhibition-207' ORDER BY p.role, p.name_as_listed").fetchall()
        self.assertEqual([(r["role"], r["name_as_listed"]) for r in roles],
                         [("artist", "배형경"), ("artist", "양태근"), ("artist", "최정화"), ("curator", "최혜경 학예연구사")])
        self.assertEqual({r["extraction_method"] for r in roles}, {"list_markup"})
        institution_curators = con.execute("SELECT COUNT(*) FROM event_participants p JOIN events e USING(event_id) WHERE e.source_event_key='exhibition-49' AND p.role='curator'").fetchone()[0]
        self.assertEqual(institution_curators, 0)

    def test_njp_offsite_venue_is_not_assumed_to_be_the_centre(self):
        sid = "wave2_njp_exhibitions"
        ctx = FakeContext(_con(sid), sid, {})
        self.assertEqual(w._gg_city(ctx, "백남준아트센터 제1전시실"), ("Yongin", "KR"))
        self.assertEqual(w._gg_city(ctx, "용인포은아트홀 야외마당"), ("Yongin", "KR"))
        self.assertEqual(w._gg_city(ctx, "상파울루 피나코테카"), (None, None))

    def test_benesse_stores_announcement_articles_without_excerpt(self):
        sid = "wave2_benesse_artsite_news"
        con = _con(sid)
        ctx = FakeContext(con, sid, {f"{w.BENESSE}/news/": BENESSE})
        w.collect(ctx)
        row = con.execute("SELECT title, published_at, article_type, excerpt, categories, lang FROM articles").fetchone()
        self.assertEqual((row["published_at"], row["article_type"], row["excerpt"], row["lang"]), ("2026-10-13", "announcement", None, "ja"))
        self.assertEqual(ctx.stats["parsed"], 1)


class RegistryTests(unittest.TestCase):
    def test_source_ids_unique_and_blocked_rows_are_static(self):
        found = runner.discover()
        ids = [r["source_id"] for r in w.SOURCES]
        self.assertEqual(len(ids), len(set(ids)))
        for r in w.SOURCES:
            self.assertIn(r["source_id"], found)
            self.assertIsNone(r["blueprint_data_id"])
            self.assertIn("Sourcebook", r["notes"])
            if r.get("disabled"):
                self.assertIn(r["operational_state"], ("blocked_access", "blocked_permission", "blocked_credentials"))
        self.assertEqual(sorted(r["source_id"] for r in w.SOURCES if r.get("disabled")),
                         ["wave2_acc_exhibitions", "wave2_busan_moca", "wave2_gwangju_museum_of_art"])


if __name__ == "__main__":
    unittest.main()

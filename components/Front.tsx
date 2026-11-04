import Link from "next/link";
import { Masthead, TopBand, TrendingNow } from "./Top";
import { Art } from "./Art";
import { Edition, Site, initials, period, splitLinks, swatch } from "@/lib/data";

function Rich({ text }: { text: string }) {
  return (
    <>
      {splitLinks(text || "").map((p, i) =>
        p.href ? (
          <a key={i} href={p.href} target="_blank" rel="noreferrer">
            {p.text}
          </a>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  );
}

function SectionTitle({ kicker, title, aside }: { kicker?: string; title: string; aside?: string }) {
  return (
    <div className="section-title">
      {kicker && <span className="kicker">{kicker}</span>}
      <h2>{title}</h2>
      <span className="rule" />
      {aside && <span className="aside">{aside}</span>}
    </div>
  );
}

export function EarlySignal({ items }: { items: any[] }) {
  if (!items?.length) return null;
  return (
    <section id="early" className="early">
      <SectionTitle kicker="EARLY SIGNAL" title="먼저 가볼 곳 — 붐비기 전에" aside="지금 열려 있거나 3주 안에 여는 전시" />
      <div className="early-grid">
        {items.map((e, i) => (
          <article key={i} className="early-card">
            <a href={e.url || "#"} target="_blank" rel="noreferrer" className="early-img">
              <Art seed={e.title} src={e.image} />
              <span className={`early-level lv-${e.level}`}>{e.level}</span>
              <span className="early-status">{e.status}</span>
            </a>
            <div className="early-body">
              <h3>
                <a href={e.url || "#"} target="_blank" rel="noreferrer">
                  {e.title}
                </a>
              </h3>
              <div className="early-where">
                {e.venue}
                {e.city ? ` · ${e.city}` : ""}
                {e.end ? ` · ~${Number(e.end.slice(5, 7))}.${Number(e.end.slice(8, 10))}` : ""}
              </div>
              <ul>
                {e.reasons.map((r: string, k: number) => (
                  <li key={k}>{r}</li>
                ))}
              </ul>
              {e.press?.length > 0 && (
                <details className="src">
                  <summary>관련 보도 {e.press.length}</summary>
                  <ul>
                    {e.press.map((p: any, k: number) => (
                      <li key={k}>
                        <a href={p.url} target="_blank" rel="noreferrer">
                          {p.title}
                        </a>{" "}
                        <span className="fine">{p.outlet}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          </article>
        ))}
      </div>
      <p className="fine">끝난 뒤 나오는 '관람객 n만 명' 기사보다 먼저: 개막 직후 보도가 붙기 시작한 전시, 이름 있는 작가, 대형 행사, 곧 끝나는 전시를 자동으로 고릅니다.</p>
    </section>
  );
}

export function Official({ items }: { items: any[] }) {
  if (!items?.length) return null;
  return (
    <section id="official" className="official">
      <SectionTitle kicker="OFFICIAL" title="미술관·갤러리가 직접 발표한 것" aside="기관 공식 소식 · 최근 2주" />
      <ul className="off-list">
        {items.map((o, i) => (
          <li key={i} className={o.weight > 1 ? "key" : ""}>
            <span className="off-org">{o.org}</span>
            <a href={o.url} target="_blank" rel="noreferrer">
              {o.title_ko || o.title}
            </a>
            <span className="off-date">{shortDate(o.date)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ArtistsInFocus({ artists }: { artists: any[] }) {
  if (!artists?.length) return null;
  return (
    <section id="artists">
      <SectionTitle kicker="ARTISTS IN FOCUS" title="지금 주목받는 작가" />
      <div className="artists">
        {artists.slice(0, 9).map((a, i) => (
          <div key={i} className="artist">
            <div className="avatar" style={{ background: swatch(a.name) }}>
              {initials(a.name)}
            </div>
            {a.story_url ? (
              <a href={a.story_url} target="_blank" rel="noreferrer">
                <b>{a.name}</b>
              </a>
            ) : (
              <b>{a.name}</b>
            )}
            <span className="cats">
              {(a.cats || []).map((c: string, j: number) => (
                <span key={j} className="cat">
                  {c}
                </span>
              ))}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function Sources({ n, list, label }: { n: number; list: any[]; label: string }) {
  if (!list?.length) return <span>{label}</span>;
  const more = Math.max(0, n - list.length);
  return (
    <details className="src">
      <summary>{label}</summary>
      <ul>
        {list.map((s: any, j: number) => (
          <li key={j}>
            <a href={s.url} target="_blank" rel="noreferrer">
              {s.outlet}
            </a>
            {s.date && <span className="fine"> · {s.date}</span>}
            {s.title && <span className="fine"> · {s.title}</span>}
          </li>
        ))}
        {more > 0 && <li className="fine">외 {more}곳</li>}
      </ul>
    </details>
  );
}

function shortDate(d?: string) {
  if (!d) return "";
  const [, m, day] = d.split("-");
  return `${Number(m)}.${Number(day)}`;
}

export function Briefing({ briefing }: { briefing: any }) {
  if (!briefing) return null;
  return (
    <section id="briefing" className="briefing">
      <SectionTitle
        kicker="TODAY'S INSIGHT"
        title="오늘의 핵심"
        aside={briefing.judged_by === "editor" ? "편집자 브리핑 · 검수 전" : "이번 주 편집 메모 + 자동 판단"}
      />
      {briefing.insights?.length > 0 && (
        <ol className="insights">
          {briefing.insights.map((t: string, i: number) => (
            <li key={i}>{t}</li>
          ))}
        </ol>
      )}
      <div className="core-list">
        {briefing.major.map((m: any, i: number) => (
          <article key={i} className="core">
            <div className="core-num">{String(i + 1).padStart(2, "0")}</div>
            <div>
              <div className="meta">
                {m.topic && <span className="tag">{m.topic}</span>}
                {m.date && <span>{m.date}</span>}
                <Sources n={m.n_sources} list={m.sources} label={`출처 ${m.n_sources}곳`} />
              </div>
              <h3>{m.headline}</h3>
              <p>{m.lead || m.brief || m.summary}</p>
              {(m.why?.length > 0 || m.criteria?.length > 0) && (
              <div className="why">
                <b>WHY</b>
                <ul>
                  {m.why.map((w: string, j: number) => (
                    <li key={j}>{w}</li>
                  ))}
                </ul>
                {m.criteria?.length > 0 && (
                  <div className="chips">
                    {m.criteria.map((c: any, j: number) => (
                      <span key={j} className="chip" title={c.evidence}>
                        {c.label}
                      </span>
                    ))}
                    {m.importance != null && <span className="chip dark">중요도 {m.importance}</span>}
                  </div>
                )}
              </div>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export function News({ stories, topics }: { stories: any[]; topics: any[] }) {
  const main = stories.filter((s) => !s.short);
  const short = stories.filter((s) => s.short);
  return (
    <section id="news">
      <SectionTitle kicker="TRENDING NEWS" title="오늘의 주요 소식" aside="최근 3일" />
      {topics?.length > 0 && (
        <div className="topics">
          {topics.map((t, i) => (
            <span key={i} className="chip">
              {t.label} · {t.count}
            </span>
          ))}
        </div>
      )}
      <ol className="stories">
        {main.map((s) => (
          <li key={s.rank} className="story-item">
            <div className="rank">{String(s.rank).padStart(2, "0")}</div>
            <div>
              <a className="story-title" href={s.url} target="_blank" rel="noreferrer">
                {s.title_ko || s.title}
              </a>
              <div className="meta">
                <span>{shortDate(s.date)}</span>
                <span className="tag">{s.topic}</span>
                {(s.tags || []).map((t: string, i: number) => (
                  <span key={i} className="tag red">
                    {t}
                  </span>
                ))}
                <Sources n={s.n_outlets} list={s.sources} label={`출처 ${s.n_outlets}`} />
              </div>
              {s.bullets?.length > 0 && (
                <ul className="bullets">
                  {s.bullets.map((b: string, i: number) => (
                    <li key={i} className={b.startsWith("→") ? "point" : ""}>
                      {b.replace(/^→\s*/, "")}
                    </li>
                  ))}
                </ul>
              )}
              {s.why?.length > 0 && (
                <p className="why-line">
                  <b>WHY</b> {s.why.join(" / ")}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
      {short.length > 0 && (
        <div className="short-news">
          <h4>짧은 소식</h4>
          <ul>
            {short.map((s) => (
              <li key={s.rank}>
                <span className="sdate">{shortDate(s.date)}</span>
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.title_ko || s.title}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

export function Exhibitions({ ex }: { ex: any }) {
  const featured = ex.featured || [];
  return (
    <section id="exhibitions">
      <SectionTitle kicker="EXHIBITIONS TO WATCH" title="이번 주 전시" aside={`지금 열린 전시 ${ex.open_count}`} />
      <div className="ex-layout">
        <div className="featured-box">
          <h2 className="big">
            FEATURED
            <br />
            THIS
            <br />
            WEEK
          </h2>
          <p>이번 주 개막했거나 2주 안에 여는 전시 가운데, 보도에서도 이름이 오르는 작가와 미술관 전시를 먼저 골랐습니다.</p>
          <div className="cities">
            {ex.cities.map((c: any, i: number) => (
              <div key={i}>
                <span>{c.city}</span>
                <b>{c.count}</b>
              </div>
            ))}
          </div>
        </div>
        <div className="ex-cards">
          {featured.slice(0, 3).map((e: any) => (
            <ExCard key={e.id} e={e} />
          ))}
        </div>
      </div>
      <div className="ex-columns">
        <ExList title="이번 주 개막" rows={ex.opened} />
        <ExList title="2주 안 개막" rows={ex.upcoming} />
        <ExList title="7일 안 종료" rows={ex.closing} />
      </div>
    </section>
  );
}

function ExCard({ e }: { e: any }) {
  return (
    <article className="ex-card">
      <div className="ex-swatch" style={e.image ? { backgroundImage: `url(${e.image})`, backgroundSize: "cover", backgroundPosition: "center" } : { background: swatch(e.title) }}>
        <span>{e.kind === "museum" ? "MUSEUM" : e.kind === "gallery" ? "GALLERY" : e.type.toUpperCase()}</span>
      </div>
      <div className="ex-body">
        <div className="kicker">
          {period(e.start, e.end)} · {e.city || ""}
        </div>
        <h3>{e.url ? <a href={e.url} target="_blank" rel="noreferrer">{e.title}</a> : e.title}</h3>
        <p>{e.venue}</p>
        {e.artists?.length > 0 && <p className="fine">{e.artists.slice(0, 4).join(", ")}</p>}
        {e.why && <p className="ex-why">{e.why}</p>}
      </div>
    </article>
  );
}

function ExList({ title, rows }: { title: string; rows: any[] }) {
  return (
    <div className="ex-list">
      <h4>
        {title} <span>{rows.length}</span>
      </h4>
      {rows.length === 0 && <p className="fine">관찰 범위에서 없음(수집 공백일 수 있음)</p>}
      <ul>
        {rows.slice(0, 8).map((e) => (
          <li key={e.id}>
            <span className="when">{period(e.start, e.end)}</span>
            {e.url ? <a href={e.url} target="_blank" rel="noreferrer">{e.title}</a> : e.title}
            <span className="where"> · {e.venue}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function GalleriesAndRookie({ galleries, rookie }: { galleries: any; rookie: any }) {
  const people = rookie.people || [];
  const watch = people.filter((p: any) => p.watch);
  const shown = watch.length >= 4 ? watch.slice(0, 6) : [...watch, ...people.filter((p: any) => !p.watch)].slice(0, 4);
  return (
    <div className="two-col">
      <section id="galleries">
        <SectionTitle kicker="GALLERY MOVES" title="갤러리 움직임" aside="최근 14일" />
        <ul className="gal">
          {galleries.openings.map((e: any) => (
            <li key={e.id}>
              <span className="tag">개막</span> <b>{e.venue}</b> — {e.url ? <a href={e.url} target="_blank" rel="noreferrer">{e.title}</a> : e.title}
              <span className="fine"> {period(e.start, e.end)}</span>
            </li>
          ))}
          {galleries.news.map((n: any, i: number) => (
            <li key={`n${i}`}>
              <span className="tag">소식</span> <b>{n.source}</b> —{" "}
              <a href={n.url} target="_blank" rel="noreferrer">
                {n.title}
              </a>
            </li>
          ))}
          {!galleries.openings.length && !galleries.news.length && <li className="fine">이번 주 수집된 갤러리 소식이 없습니다.</li>}
        </ul>
      </section>
      <section id="rookie">
        <SectionTitle kicker="ROOKIE RADAR" title="지켜볼 신진" aside="공식 선정 · 초기 경력 · 후속 지원 확인" />
        {shown.length === 0 && <p className="fine">최근 30일 판단한 수상·선정이 없습니다.</p>}
        <div className="rookies">
          {shown.map((p: any, i: number) => (
            <article key={i} className={`rookie ${p.watch ? "" : "ref"}`}>
              <div className="avatar sm" style={{ background: swatch(p.name) }}>
                {initials(p.name)}
              </div>
              <div>
                <div className="meta">
                  <span className="tag red">{p.watch ? p.status : `참고 · ${p.status}`}</span>
                  <span>상의 무게 {p.weight.level}</span>
                </div>
                <b>{p.name}</b> <span className="fine">{p.genre || ""}</span>
                <p>{p.award}</p>
                {p.why && <p className="fine">왜: {p.why}</p>}
                <div className="checks">
                  {p.checks.map((c: any, j: number) => (
                    <span key={j} className={`check ${c.ok === true ? "ok" : c.ok === false ? "no" : "un"}`} title={c.detail}>
                      {CHECK_LABEL[c.rule.slice(0, 3)] || c.rule.slice(0, 3)}
                    </span>
                  ))}
                </div>
              </div>
            </article>
          ))}
        </div>
        {rookie.awards?.length > 0 && (
          <details className="awards">
            <summary>이번 달 판단한 수상·선정 {rookie.awards.length}건 — 상의 무게</summary>
            <table>
              <thead>
                <tr>
                  <th>상</th>
                  <th>무게</th>
                  <th>트랙</th>
                  <th>수상자</th>
                </tr>
              </thead>
              <tbody>
                {rookie.awards.map((a: any, i: number) => (
                  <tr key={i}>
                    <td>{a.url ? <a href={a.url} target="_blank" rel="noreferrer">{a.award}</a> : a.award}</td>
                    <td title={a.weight.reasons.join("\n")}>
                      {a.weight.level} {a.weight.points}
                    </td>
                    <td>{a.track}</td>
                    <td>{a.winners.join(", ") || "명단 미확인"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
        <Link className="more" href="/rookie">
          누적 관찰 명단 →
        </Link>
      </section>
    </div>
  );
}

const CHECK_LABEL: Record<string, string> = { R01: "공식 선정", R02: "초기 경력", R03: "독립 확인", R04: "반복 선정", R05: "후속 지원" };
const CRIT_LABEL: Record<string, string> = { review: "리뷰", criticism: "비평", interview: "인터뷰" };

export function CriticismAndFairs({ criticism, fairs }: { criticism: any[]; fairs: any[] }) {
  return (
    <div className="two-col" id="market">
      <section>
        <SectionTitle kicker="CRITICISM" title="이번 주 비평·리뷰" />
        <ul className="crit">
          {criticism.map((c, i) => (
            <li key={i}>
              <span className="tag">{CRIT_LABEL[c.type] || c.type}</span>{" "}
              <a href={c.url} target="_blank" rel="noreferrer">
                {c.title_ko || c.title}
              </a>
              <span className="fine">
                {" "}
                · {c.outlet} · {c.date}
              </span>
              {c.title_ko && <div className="ko">원문: {c.title}</div>}
            </li>
          ))}
          {!criticism.length && <li className="fine">이번 주 수집된 비평이 없습니다.</li>}
        </ul>
      </section>
      <section>
        <SectionTitle kicker="FAIRS & BIENNIALS" title="페어·비엔날레" aside="60일" />
        <ul className="crit">
          {fairs.map((f) => (
            <li key={f.id}>
              <span className={`tag ${f.status === "진행 중" ? "red" : ""}`}>
                {f.status} {f.status === "개막 예정" ? `D-${f.d_day}` : f.status === "진행 중" ? `폐막 D-${f.d_day}` : ""}
              </span>{" "}
              <b>{f.title}</b>
              <span className="fine"> · {period(f.start, f.end)} {f.city || ""}</span>
            </li>
          ))}
          {!fairs.length && <li className="fine">60일 안의 페어·비엔날레가 수집되지 않았습니다.</li>}
        </ul>
      </section>
    </div>
  );
}

export function Archive({ site, edition, date }: { site: Site; edition: Edition; date: string }) {
  return (
    <nav className="archive" id="archive">
      <span>지난 호</span>
      {site.dates.map((d) => (
        <Link key={d} href={d === site.asof ? `/${edition.slug}` : `/${edition.slug}/${d}`} className={d === date ? "on" : ""}>
          {d.slice(5).replace("-", ".")}
        </Link>
      ))}
    </nav>
  );
}

export function Footer({ site }: { site: Site }) {
  return (
    <footer className="footer">
      <div className="brand light">ARTREND</div>
      <nav>
        <Link href="/logic">판단 기준</Link>
        <Link href="/rookie">루키 관찰 명단</Link>
      </nav>
      <p>
        데이터 생성 {site.generated_at.slice(0, 16).replace("T", " ")} · {site.update_schedule} · 모든 문장은 편집 승인 전 내부 초안입니다. 기사 본문과 이미지는 싣지
        않으며, 가격·조회수는 예술적 가치로 쓰지 않습니다.
      </p>
    </footer>
  );
}

export function FrontPage({ site, edition, page }: { site: Site; edition: Edition; page: any }) {
  return (
    <main>
      <Masthead site={site} edition={edition} date={page.date} page={page} />
      <TrendingNow items={page.top?.trending} />
      <TopBand page={page} edition={edition} />
      <EarlySignal items={page.early} />
      <ArtistsInFocus artists={page.artists} />
      <Briefing briefing={page.briefing} />
      <Official items={page.official} />
      <News stories={page.stories} topics={page.topics} />
      <Exhibitions ex={page.exhibitions} />
      <GalleriesAndRookie galleries={page.galleries} rookie={page.rookie} />
      <CriticismAndFairs criticism={page.criticism} fairs={page.fairs} />
      <Archive site={site} edition={edition} date={page.date} />
      <Footer site={site} />
    </main>
  );
}

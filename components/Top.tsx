import Link from "next/link";
import { Edition, Site } from "@/lib/data";
import { Art } from "./Art";
import { HeroCarousel } from "./HeroCarousel";

const WEEKDAY = ["일요일", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일"];
const SHORT: Record<string, string> = { KR: "KR", JP: "JP", AMERICAS: "US", EUROPE: "EU" };

function longDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return { weekday: WEEKDAY[new Date(Date.UTC(y, m - 1, d)).getUTCDay()], date: `${y}년 ${m}월 ${d}일` };
}

function updateTime(schedule: string) {
  const m = /(\d{1,2}):(\d{2})/.exec(schedule || "");
  if (!m) return schedule;
  const h = Number(m[1]);
  return `${h < 12 ? "오전" : "오후"} ${h % 12 || 12}:${m[2]} 업데이트`;
}

function CalendarIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <rect x="3.5" y="5" width="17" height="15" rx="1.5" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="M20 12a8 8 0 1 1-2.34-5.66M20 4v5h-5" />
    </svg>
  );
}

export function Masthead({ site, edition, date, page }: { site: Site; edition: Edition; date: string; page: any }) {
  const { weekday, date: long } = longDate(date);
  const latest = date === site.asof;
  return (
    <header className="mh">
      <div className="mh-top">
        <div className="mh-meta">
          <div className="mh-item">
            <CalendarIcon />
            <span>
              <b>{weekday}</b>
              <small>{long}</small>
            </span>
          </div>
          <div className="mh-item">
            <RefreshIcon />
            <span>
              <b>{updateTime(site.update_schedule)}</b>
              <small>
                {edition.ko} · 이번 주 소식 {page.stats?.stories_7d ?? 0}건
              </small>
            </span>
          </div>
        </div>
        <Link href={`/${edition.slug}`} className="mh-logo">
          <span>.artrend</span>
          <small>ART TREND MAGAZINE</small>
        </Link>
        <nav className="mh-ed" aria-label="에디션">
          {site.editions.map((e) => (
            <Link key={e.code} href={`/${e.slug}`} className={e.code === edition.code ? "on" : ""} title={e.ko}>
              {SHORT[e.code] || e.code}
            </Link>
          ))}
        </nav>
      </div>
      <nav className="mh-nav">
        <details className="mh-menu">
          <summary aria-label="메뉴">
            <span />
            <span />
          </summary>
          <div>
            <Link href="/logic">판단 기준</Link>
            <Link href="/rookie">루키 관찰 명단</Link>
            <a href="#archive">지난 호</a>
          </div>
        </details>
        <a href="#briefing" className="on">
          Insight
        </a>
        <a href="#news">News</a>
        <a href="#exhibitions">Exhibitions</a>
        <a href="#artists">Artists</a>
        <a href="#galleries">Galleries</a>
        <a href="#rookie">Rookie</a>
        <a href="#market">Market</a>
        <Link href="/logic" className="mh-logic">
          판단 기준
        </Link>
      </nav>
      {!latest && (
        <div className="archive-note">
          지난 호를 보고 있습니다 · <Link href={`/${edition.slug}`}>최신호로</Link>
        </div>
      )}
    </header>
  );
}

export function TrendingNow({ items }: { items: any[] }) {
  if (!items?.length) return null;
  return (
    <section className="tn" aria-label="Trending now">
      <div className="tn-head">TRENDING NOW · 지금 가면 앞서가는 곳</div>
      <ol className="tn-list">
        {items.map((t, i) => (
          <li key={i}>
            <Art seed={t.title} className="tn-thumb" src={t.image} />
            <div>
              <a href={t.url || "#news"} target={t.url ? "_blank" : undefined} rel="noreferrer" className="tn-title">
                {t.title}
              </a>
              <span className="tn-ago">
                <b>{t.topic}</b> · {t.ago}
                {t.reason ? ` · ${t.reason}` : ""}
              </span>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Keywords({ list }: { list: any[] }) {
  return (
    <div className="hot">
      <span className="hot-label">↗ HOT TRENDS</span>
      <div className="hot-chips">
        {list.map((k) => (
          <details key={k.label} className={`kw kind-${k.kind}`}>
            <summary>{k.label}</summary>
            <div className="kw-pop">
              <b>{k.label}</b>
              <span className="kw-note">{k.note}</span>
              {k.examples?.length > 0 && (
                <ul>
                  {k.examples.map((x: any, i: number) => (
                    <li key={i}>
                      {x.url ? (
                        <a href={x.url} target="_blank" rel="noreferrer">
                          {x.title}
                        </a>
                      ) : (
                        x.title
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </details>
        ))}
        {list.length < 3 && <span className="hot-thin">이번 주 뚜렷하게 뜬 키워드가 적습니다</span>}
        <Link href="/rookie" className="kw kw-link">
          Rookie
        </Link>
      </div>
    </div>
  );
}

function SideCard({ card, tone, href }: { card: any; tone: "rookie" | "gallery"; href: string }) {
  if (!card) return <div className={`side side-${tone} side-empty`} />;
  return (
    <a className={`side side-${tone}`} href={card.url || href} target={card.url ? "_blank" : undefined} rel="noreferrer">
      <Art seed={card.title} variant={tone === "rookie" ? "blocks" : "circle"} className="side-art" />
      <div className="side-body">
        <span className="side-label">{card.label}</span>
        <h3>{card.title}</h3>
        {card.dek && <p>{card.dek}</p>}
        {tone === "rookie" && <span className="side-link">ROOKIE RADAR ↗</span>}
      </div>
    </a>
  );
}

function TrendingArtists({ artists }: { artists: any[] }) {
  const list = (artists || []).slice(0, 4);
  if (!list.length) return <aside className="ta" />;
  const [first, ...rest] = list;
  const kicker = (a: any) => [...(a.cats || []), a.where].filter(Boolean).join(" · ");
  return (
    <aside className="ta">
      <div className="ta-head">TRENDING ARTISTS</div>
      <a className="ta-first" href={first.story_url || "#artists"} target={first.story_url ? "_blank" : undefined} rel="noreferrer">
        <Art seed={first.name} variant="bar" className="ta-art" />
        <div className="ta-over">
          <span>{kicker(first)}</span>
          <b>{first.name}</b>
        </div>
      </a>
      <ol start={2}>
        {rest.map((a, i) => (
          <li key={a.name}>
            <span className="ta-n">{i + 2}</span>
            <div>
              <span className="ta-cat">{kicker(a)}</span>
              {a.story_url ? (
                <a href={a.story_url} target="_blank" rel="noreferrer">
                  {a.name}
                </a>
              ) : (
                <b>{a.name}</b>
              )}
            </div>
          </li>
        ))}
      </ol>
      <a href="#artists" className="ta-all">
        See all artists ›
      </a>
    </aside>
  );
}

export function TopBand({ page, edition }: { page: any; edition: Edition }) {
  const top = page.top || {};
  const heads = (top.hero || []).map((i: number) => page.headlines[i]).filter(Boolean);
  return (
    <section className="band" id="trend">
      <div className="band-in">
        <Keywords list={page.keywords || []} />
        <div className="band-grid">
          <div className="band-left">
            <SideCard card={top.rookie} tone="rookie" href="#rookie" />
            <SideCard card={top.gallery} tone="gallery" href="#galleries" />
          </div>
          <HeroCarousel heads={heads} label={`TODAY'S INSIGHT · ${edition.en.toUpperCase()}`} date={page.date.replace(/-/g, ".")} />
          <TrendingArtists artists={page.artists} />
        </div>
        <p className="band-fine">
          헤드라인과 키워드는 전시·수상·비평·뉴스 데이터를 규칙으로 읽은 자동 판단입니다. 키워드는 지난 4주보다 이번 주에 뚜렷이 늘어난 미술 주제·행사·작가만
          싣습니다. <Link href="/logic">판단 기준</Link>
        </p>
      </div>
    </section>
  );
}

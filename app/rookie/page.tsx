import Link from "next/link";
import { getSite, getWatchlist } from "@/lib/data";

const MARK: Record<string, string> = { true: "✓", false: "✕", null: "?" };
const LABEL: Record<string, string> = { R01: "공식 선정", R02: "초기 경력", R03: "독립 확인", R04: "반복 선정", R05: "후속 지원" };

export default function RookiePage() {
  const site = getSite();
  const rows = getWatchlist();
  const ko = Object.fromEntries(site.editions.map((e) => [e.code, e.ko]));
  return (
    <main className="doc wide">
      <Link href={`/${site.editions[0].slug}`} className="brand">ARTREND</Link>
      <h1>루키 관찰 명단</h1>
      <p>수상·선정 소식을 읽고 상의 무게와 신진 조건(공식 선정 · 초기 경력 · 독립 확인 · 후속 지원)을 확인해 누적한 명단입니다. 루키 확정이 아니라 '계속 지켜볼 이유'의 기록입니다.</p>
      <table>
        <thead><tr><th>이름</th><th>에디션</th><th>처음 본 날</th><th>상·선정</th><th>상의 무게</th><th>판단</th><th>조건</th><th>왜</th></tr></thead>
        <tbody>
          {rows.map((r: any) => (
            <tr key={r.name}>
              <td><b>{r.name}</b></td><td>{ko[r.edition] || r.edition}</td><td>{r.first_seen}</td><td>{r.awards.join(" / ")}</td>
              <td>{r.level}</td><td>{r.status}</td>
              <td>{r.checks.map((c: any) => <span key={c.rule} title={c.detail} className={`check ${c.ok === true ? "ok" : c.ok === false ? "no" : "un"}`}>{(LABEL[c.rule.slice(0, 3)] || c.rule.slice(0, 3))}{MARK[String(c.ok)]}</span>)}</td>
              <td className="fine">{r.why}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}

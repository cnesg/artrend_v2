import Link from "next/link";
import { getLogic, getSite } from "@/lib/data";

export default function LogicPage() {
  const site = getSite();
  const logic = getLogic();
  return (
    <main className="doc">
      <Link href={`/${site.editions[0].slug}`} className="brand">ARTREND</Link>
      <h1>판단 기준</h1>
      <p>ARTREND는 소식을 나열하지 않고, 아래 규칙으로 '무엇이 왜 중요한가'를 판단합니다. 기준은 ARTREND Logic·Data·Agent Blueprint v1.2(01 분석로직, 10 루키발굴, 22 사건세부기준, 24–27 헤드라인)를 따릅니다.</p>
      <h2>트렌드 헤드라인 신호</h2>
      <ul>{logic.trend_signals.map((t: string, i: number) => <li key={i}>{t}</li>)}</ul>
      <h2>HOT TRENDS 키워드</h2>
      <ul>{(logic.keyword_rules || []).map((t: string, i: number) => <li key={i}>{t}</li>)}</ul>
      <h2>주요 소식 중요도</h2>
      <p>'여러 곳이 보도했다'만으로 고르지 않습니다. 제목·요약·본문 핵심 문장에서 아래 기준을 찾아 점수를 매깁니다.</p>
      <table><thead><tr><th>기준</th><th>점수</th></tr></thead>
        <tbody>{logic.importance.map((c: any) => <tr key={c.id}><td>{c.label}</td><td>{c.weight}</td></tr>)}</tbody></table>
      <p>자동 판단 등급: {logic.auto_levels.map((l: any) => `${l.label} ${l.min}점 이상`).join(" · ")}</p>
      <h2>루키 판단</h2>
      <ul>{logic.rookie_rules.map((t: string, i: number) => <li key={i}>{t}</li>)}</ul>
      <p>상의 무게 — 주최 유형 점수: {Object.entries(logic.organizer_points).map(([k, v]) => `${k} ${v}`).join(" · ")}. 10년 이상 운영·전문가 심사·국제 심사·후속 전시·매입·상금 1천만원 이상 각 +1. 6점 이상 높음, 3점 이상 보통.</p>
      <h2>원칙</h2>
      <ul>{logic.policy.map((t: string, i: number) => <li key={i}>{t}</li>)}</ul>
    </main>
  );
}

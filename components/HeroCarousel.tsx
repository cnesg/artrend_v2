"use client";

import { useState } from "react";
import { Art } from "./Art";

// '[text](url)' -> anchors (the data's only markup)
function linked(s: string) {
  const out: React.ReactNode[] = [];
  const re = /\[([^\]]+)\]\(([^)\s]+)\)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    out.push(
      <a key={m.index} href={m[2]} target="_blank" rel="noreferrer">
        {m[1]}
      </a>,
    );
    last = m.index + m[0].length;
  }
  out.push(s.slice(last));
  return out;
}

type Head = { image?: string | null; title: string; dek: string; axis: string; power_label: string; points?: string[]; tags?: string[]; about?: string; what?: string[] };

export function HeroCarousel({ heads, label, date }: { heads: Head[]; label: string; date: string }) {
  const [i, setI] = useState(0);
  if (!heads.length) return <div className="hero hero-empty">이 날짜에 수집된 데이터가 없습니다. 수집 공백이며 활동이 없다는 뜻이 아닙니다.</div>;
  const h = heads[i];
  const go = (d: number) => setI((i + d + heads.length) % heads.length);
  return (
    <div className="hero-wrap">
      <article className="hero">
        <Art seed={h.title} variant="stripes" className="hero-art" src={h.image} />
        <div className="hero-shade" />
        <div className="hero-top">
          <span className="hero-label">{label}</span>
          {heads.length > 1 && (
            <span className="hero-nav">
              <button aria-label="이전" onClick={() => go(-1)}>
                ‹
              </button>
              <span className="hero-count">
                {i + 1}/{heads.length}
              </span>
              <button aria-label="다음" onClick={() => go(1)}>
                ›
              </button>
            </span>
          )}
        </div>
        <div className="hero-body">
          {h.tags && h.tags.length > 0 && (
            <div className="hero-tags">
              {h.tags.map((t) => (
                <span key={t}>#{t.replace(/\s/g, "")}</span>
              ))}
            </div>
          )}
          <h1>{h.title}</h1>
          <p className="hero-dek">{h.dek}</p>
          {h.points && h.points.length > 0 && (
            <ul className="hero-points">
              {h.points.map((p, k) => (
                <li key={k}>{p}</li>
              ))}
            </ul>
          )}
          <div className="hero-meta">
            <span>{date}</span>
            <span>{h.axis}</span>
            <span>{h.power_label}</span>
          </div>
        </div>
      </article>
      {(h.about || (h.what && h.what.length > 0)) && (
        <details className="hero-more" key={i}>
          <summary>무슨 일인가 · 자세히</summary>
          {h.about && <p>{h.about}</p>}
          {h.what && h.what.length > 0 && (
            <ul>
              {h.what.map((w, k) => (
                <li key={k}>{linked(w)}</li>
              ))}
            </ul>
          )}
        </details>
      )}
    </div>
  );
}

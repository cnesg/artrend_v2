import fs from "node:fs";
import path from "node:path";

// All pages read the JSON feed written by `python -m artrend_mag.cli web` (copied into ./data by scripts/daily_update.sh).
const DATA = path.join(process.cwd(), "data");

export type Edition = { code: string; slug: string; ko: string; en: string };
export type Site = { asof: string; dates: string[]; editions: Edition[]; generated_at: string; update_schedule: string; publishable: boolean };

function read<T>(...parts: string[]): T {
  return JSON.parse(fs.readFileSync(path.join(DATA, ...parts), "utf-8")) as T;
}

export function getSite(): Site {
  return read<Site>("site.json");
}

export function editionBySlug(slug: string): Edition | undefined {
  return getSite().editions.find((e) => e.slug === slug);
}

export function getPage(code: string, date: string): any | null {
  const file = path.join(DATA, date, `${code}.json`);
  return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf-8")) : null;
}

export function getLogic(): any {
  return read("logic.json");
}

export function getWatchlist(): any[] {
  return read("rookie_watchlist.json");
}

const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];
export function koDate(iso: string): string {
  const wd = new Date(`${iso}T12:00:00Z`).getUTCDay();
  return `${iso.replace(/-/g, ".")} (${WEEKDAY[wd]})`;
}

export function period(start?: string | null, end?: string | null): string {
  const f = (s?: string | null) => (s ? s.slice(5).replace("-", ".") : "");
  if (start && end) return `${f(start)} – ${f(end)}`;
  if (start) return `${f(start)} –`;
  if (end) return `– ${f(end)}`;
  return "기간 미상";
}

// Deterministic color swatches stand in for images (no image rights are cleared yet).
const SWATCH = ["#c8371f", "#1f2f4a", "#2f4a3a", "#e8d9c0", "#6b2a3a", "#d9a441", "#3c3c3c", "#8aa1b1"];
export function swatch(seed: string): string {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return SWATCH[h % SWATCH.length];
}

export function initials(name: string): string {
  const t = name.trim();
  if (/^[\u3131-\uD79D]/.test(t)) return t.slice(0, 1);
  return t.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
}

// "[label](url)" markdown links inside evidence strings -> safe parts for rendering.
export function splitLinks(text: string): { text: string; href?: string }[] {
  const out: { text: string; href?: string }[] = [];
  const re = /\[([^\]]+)\]\((https?:[^)\s]+)\)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push({ text: text.slice(last, m.index) });
    out.push({ text: m[1], href: m[2] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}

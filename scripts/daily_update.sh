#!/bin/bash
# ARTREND daily update — starts 07:00 KST, holds the push until PUBLISH_AT (default 08:30 KST).
# If the run finishes later than PUBLISH_AT it pushes immediately.
#   1. collect new public data (incremental, robots/terms-respecting) and translate new foreign titles (local model)
#   2. read top/award articles and score them            (cli brief)
#   3. rebuild the Obsidian vault and the web JSON feed  (cli vault, cli web)
#   4. copy the feed into this repo and push → Vercel rebuilds automatically
# Requires: ARTREND_PIPELINE = path to the pipeline checkout that holds db/ and .env (never committed).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PIPE="${ARTREND_PIPELINE:-$REPO/pipeline}"
PY="$PIPE/.venv/bin/python"
TODAY="$(TZ=Asia/Seoul date +%F)"
LOG="$PIPE/runs/daily_$TODAY.log"
mkdir -p "$PIPE/runs"
cd "$PIPE"
{
  echo "== $(date) ARTREND daily $TODAY"
  "$PY" -m artrend_mag.cli collect --mode incremental || echo "collect: partial failure (continuing with collected data)"
  # today's window first (new titles + older-pipeline records), then a bounded catch-up of the backlog
  "$PY" -m artrend_mag.translate_recent > /dev/null || echo "translate (recent): failed (foreign titles stay in the original language)"
  "$PY" -m artrend_mag.translation --source-table articles --limit 1500 > /dev/null || echo "translate (backlog): failed"
  "$PY" -m artrend_mag.cli brief --asof "$TODAY" || echo "brief: failed (pages fall back to automatic judgements)"
  if [ -f "editorial/notes_$TODAY.json" ]; then "$PY" -m artrend_mag.cli brief --asof "$TODAY" --check-names || true; fi
  "$PY" -m artrend_mag.cli vault --asof "$TODAY"
  "$PY" -m artrend_mag.cli web --asof "$TODAY" --out "$REPO/data"
  PUBLISH_AT="${PUBLISH_AT:-08:30}"
  NOW=$(TZ=Asia/Seoul date +%s)
  TARGET=$(TZ=Asia/Seoul date -j -f "%F %H:%M:%S" "$TODAY $PUBLISH_AT:00" +%s)
  if [ "$NOW" -lt "$TARGET" ]; then echo "holding push until $PUBLISH_AT KST"; sleep $((TARGET - NOW)); fi
  cd "$REPO"
  git add data
  if git diff --cached --quiet; then echo "no data change"; else
    git commit -m "data: daily update $TODAY" && git push
  fi
  echo "== done $(date)"
} >> "$LOG" 2>&1

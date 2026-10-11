#!/usr/bin/env bash
# Write the live articles as ready-made files (nishpaksh/feed.py) and replace the `feed` branch with
# them: one commit, force-pushed, so the branch never grows. The previous files are checked out first so
# only articles that changed are read from the database (its manifest.json). The reading site (site/)
# reads them from GitHub's CDN and falls back to Supabase, so a failure here only costs speed.
set -euo pipefail
REMOTE="${FEED_REMOTE:-https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git}"
DIR="${FEED_DIR:-feedout}"
rm -rf "$DIR"
if ! git clone --quiet --depth 1 --branch feed "$REMOTE" "$DIR" 2>/dev/null; then
  mkdir -p "$DIR"
fi
rm -rf "$DIR/.git"
python -m nishpaksh.feed --dir "$DIR"
git init --quiet -b feed "$DIR"
git -C "$DIR" add -A
git -C "$DIR" -c user.name="nishpaksh-feed" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
  commit --quiet -m "Feed $(date -u '+%Y-%m-%d %H:%M')"
# a push that fails once (network, a busy GitHub) is tried again: a feed left an hour old is what readers saw as
# "the notification came, the article did not" (owner, Oct 11 2026)
pushed=0
for try in 1 2 3; do
  if git -C "$DIR" push --quiet --force "$REMOTE" HEAD:feed; then pushed=1; break; fi
  echo "feed push failed (try $try of 3)"; sleep $((try * 6))
done
if [ "$pushed" != 1 ]; then echo "feed NOT published"; exit 1; fi
echo "feed pushed"

# The push is not the moment readers can see it: raw.githubusercontent.com serves the old files for a while after a
# force-push. The notifications go out right after this step, so wait (at most FEED_LIVE_WAIT seconds) until the CDN
# serves THIS export (its generated_at). If it never does, the site still shows the new articles: it asks the
# database for anything newer than the feed (site/index.html, loadCards).
if [ -z "${FEED_REMOTE:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ] && [ "${FEED_LIVE_WAIT:-240}" -gt 0 ]; then
  want=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['generated_at'])" "$DIR/en.json" 2>/dev/null || true)
  url="https://raw.githubusercontent.com/${GITHUB_REPOSITORY}/feed/en.json"
  waited=0; got=""
  while [ -n "$want" ] && [ "$waited" -lt "${FEED_LIVE_WAIT:-240}" ]; do
    got=$(curl -fsS --max-time 20 -H 'Cache-Control: no-cache' "${url}?cb=$(date +%s%N)" 2>/dev/null \
          | python3 -c "import json,sys; print(json.load(sys.stdin).get('generated_at',''))" 2>/dev/null || true)
    if [ "$got" = "$want" ]; then echo "feed live after ${waited}s"; break; fi
    sleep 10; waited=$((waited + 10))
  done
  if [ -n "$want" ] && [ "$got" != "$want" ]; then
    echo "feed not served yet after ${waited}s (wanted $want, got '${got:-nothing}'): the site reads newer articles from the database"
  fi
fi
echo "feed published"

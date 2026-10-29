#!/usr/bin/env bash
# Builds the folder GitHub Pages serves (_site): the site, the voice module, the audio made so far, and the
# share pages (nishpaksh/sharepages.py: /s/<id>/ and /hi/s/<id>/, the link previews of shared articles) taken
# from the feed branch. Every Pages deploy (site.yml, audio.yml) uses this, because a deploy replaces the whole
# site: one that left a part out would take it offline.
set -euo pipefail
REPO_URL="https://github.com/${GITHUB_REPOSITORY}.git"
rm -rf _site && cp -r site _site && mkdir -p _site/audio _site/live
# "Understand by talking": the voice module and its intro words (and the intro recordings, once made)
cp live/talk.js live/intro.json _site/live/
cp live/intro-*.m4a _site/live/ 2>/dev/null || true
if git clone --quiet --depth 1 --branch audio "$REPO_URL" /tmp/audio 2>/dev/null; then
  cp /tmp/audio/*.m4a /tmp/audio/*.json _site/audio/ 2>/dev/null || true
fi
# the share pages: a missing feed branch or folder only means no previews, never a failed deploy
if git clone --quiet --depth 1 --branch feed "$REPO_URL" /tmp/feed 2>/dev/null; then
  if [ -d /tmp/feed/s ]; then mkdir -p _site/s && cp -r /tmp/feed/s/. _site/s/; fi
  if [ -d /tmp/feed/hi/s ]; then mkdir -p _site/hi/s && cp -r /tmp/feed/hi/s/. _site/hi/s/; fi
fi
echo "site built: $(find _site/s _site/hi/s -name index.html 2>/dev/null | wc -l) share pages"

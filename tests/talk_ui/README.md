Browser tests for the "Understand by talking" look (button, banner, card, floating button).
They open the real site/index.html in Chromium with the feed and Supabase stubbed and live/talk.js replaced by a mock
that the test drives by hand (no microphone, no Gemini). Not part of CI (needs a browser):

    npm i -D playwright && npx playwright install chromium
    SHOTS=/tmp/shots node tests/talk_ui/flow_float.cjs && node tests/talk_ui/flow_rest.cjs

Every line prints PASS or FAIL.

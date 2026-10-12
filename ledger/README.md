# Ledger

One record per hourly run, written after the desk step (`python -m nishpaksh.ledger`, schema version 1).
Purpose: embedding use and outlet yield were hard to see; this keeps them, run after run, in the repository so
the next session starts from numbers.

## Files
- `LEDGER.md`: the readable summary of the last 8 days, regenerated every run.
- `runs-YYYY-MM.jsonl`: one JSON object per run (kept 120 days). Fields below.

## Fields of a run record
- `run`, `at` (UTC), `ist`, `pt_day` (the quota day the run belongs to: Pacific, like Google's quotas), `trigger`, `seconds`.
- `intake`: `new` articles stored this run, `found_by_search`, `by_outlet` (new articles per outlet this run).
- `embed`: `used_today` (the quota counter: embedding texts used so far this quota day, all keys), `used_by_key` (the same per
  Gemini key: k1, k2, k3), `left_today`
  (what the router thought was left, after its reserves), `pace_left_now` (what the pacing curve allows now), and
  `this_run`, from `stories.EMBED_STATS`:
  `budget` (texts this run may use) = everything left today minus a reserve for each later run (`embed_reserve_per_run`),
  never below `embed_min_texts_per_run` and never above the pacing curve; `left_today`, `runs_left`, `pace_now`,
  `waiting_new` / `waiting_old` (articles without a vector: new ones / read ones on another model's vector),
  `chosen_new` / `chosen_old` (what the budget took), `embedded` (texts actually sent), `by_outlet` (embedded per outlet),
  `waiting_before` / `waiting_after`, `held_world` (world-outlet articles kept back by `worldgate.hold`).
- `outlets`: per outlet `[articles in the 72 h window, of them embedded, of them in a story with 3+ independent
  outlets]`; the yield is the third over the second.
- `yield_at_start`: the yield share `stories._yields` used to order this run's embedding (0.5 = too few to judge).
- `pipeline`: counts of the run's stages (grouped, rated, queue, extracted, analysed, qualifying, settled ...).
- `quota_left`, `tier_calls`: Gemini quota left per tier at the end of the run, and the calls made, by outcome.
- `desk`: the writing desk's record of the hour: `published` (story ids), `seats` (general / beat left), `ready`,
  `ready_beat`, `skipped`, `beat_seat`, `short`.
- `express`: the express lane's funnel for the run (appears when the lane runs): counts per step and, under
  `excluded`, how many headlines each exclusion list kept out.
- `problems`: the run's health problems and failed steps.

## Reading it
- Is embedding really the bottleneck? Compare `used_today` at day's end with 3,000, and `waiting_after` at the
  last runs of the day: articles still waiting then never got a vector.
- Which outlets are worth their texts? `outlets` yield per outlet, over days.
- Is the express slice (`embed_daily_cap`, config/express.yaml) right? `express.embedded` per day against
  `used_today`, and the yield of express articles once recorded.

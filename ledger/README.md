# Ledger

One record per hourly run, written after the desk step (`python -m nishpaksh.ledger`, schema version 1).
Purpose: embedding use and outlet yield were hard to see; this keeps them, run after run, in the repository so
the next session starts from numbers.

## Pool and rhythm (Oct 29 2026)

`pool`: `mode` (light, full, prime) of the run; `at_desk_start` ready stories when the job's first desk run began;
`write_allowance` how many that desk run could publish (None: every seat); `after_first_desk` the count that decided light or full;
`read` stories the run read; `end` ready at the end of the job; `desk_runs` and `desk_seconds` of the job's desk runs.
`rhythm`: `hours_24h` articles written in each of the 24 completed hours before this record (oldest first), `empty_hours`,
`mean_per_hour`, `sd_per_hour`, `longest_gap_min` between desk runs that wrote something, `first_in_job_min` from the job's start to its
first article. Times are those of the desk's record (the end of its run), a few minutes before the feed shows the article.
Consistency is the goal: no empty hours and a small spread, then more articles.

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
  `ready_beat`, `skipped`, `beat_seat`, `beat_seat_empty`, `short`.
- `express`: the express lane's funnel for the run (appears when the lane runs). Counts per step, in order:
  `taken` (new links from express feeds that were downloaded), `intake_excluded` (kept out by code before the page was
  fetched) and `intake_over_cap`, `unreadable` (page not fully readable: option B), `asked` (headlines the model
  answered, each asked twice), `not_lane` (no lane, or the two answers differed), `passed` and `passed_<lane>`,
  `embedded` (texts used from the day's express slice), `calls` (model calls). `excluded` {list: n} and
  `excluded_terms` {"list:word": n} count the code exclusions at every step. `now` holds readings that are not
  sums: `cap_left` (of `embed_daily_cap` today), `allowance` (what the pacing curve opens now), `passed_waiting`
  (passed, waiting for slice room), `undecided` (headlines still to ask).
- `shadow` (Oct 29 2026): what tidy / fusion / insert WOULD have done to the pages published or matured this run (nothing is
  changed): `stories`, `lines`, `pairs`, `outcomes` (same / covered / overlap / conflict / distinct), `folded`, `stories_with_fold`,
  `to_one_sentence`, `inspector_repeats` (what the current code counts), `weekday_errors`, `also_lines`, `also_would_insert`,
  `also_why_not`, and up to 5 `sample_folds` (kept / dropped / reader), `sample_would_fold` (folds the code proposed that the reader did not confirm),
  `sample_overlaps`, `sample_inserted` (with the story's headline, lead and the line it would sit next to) to READ. Oct 30 2026: a fold
  needs the local reader to say the kept line holds all the dropped line says (`reader` true/false, `unverified`, `reader_refused`,
  `would_fold` = folded + both), a line partly in another script is never judged, an inserted line must also fit the story's time
  and not repeat another inserted line; `seconds` is what the shadow step cost. Any sampled fold or insertion that is
  not right is a false positive: the systems stay off until a day of samples has none.
- `problems`: the run's health problems and failed steps.

## Reading it
- Is embedding really the bottleneck? Compare `used_today` at day's end with 3,000, and `waiting_after` at the
  last runs of the day: articles still waiting then never got a vector.
- Which outlets are worth their texts? `outlets` yield per outlet, over days.
- Is the express slice (`embed_daily_cap`, config/express.yaml) right? `express.embedded` per day against
  `used_today`, and the yield of express articles once recorded.

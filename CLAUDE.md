# Nishpaksh (निष्पक्ष) — handover for the next session

Hourly, bilingual (English + Hindi, `?lang=hi`) Indian news site that writes each story once, from
every outlet that covered it, and colours every sentence by how well it is supported. Owner: Aakash.

## How to work with the owner
- **Order: philosophy → structure → coding.** Discuss principles first, then a structure he approves,
  then build. In the coding phase make the implementation decisions yourself.
- **Be efficient.** No hours of testing or polling live runs. Test on stored real data
  (`tools/replay.py`), push, and check the next run's results in one look.
- He is truthful and disagreeable: give honest pushback, explain trade-offs plainly, no flattery.
- **The models are simple (owner, Oct 7 2026).** Old, small, free-tier models: design every fix for them.
  Code does the work wherever it can; a model gets one small, concrete question (a fixed choice like
  same/different, short batches, worked examples including the traps, "if unsure: the safe answer");
  a model answer that could make something green or merge facts is asked twice (order swapped) and
  checked by code; a writing rule is enforced by code, never left to the prompt alone.
- Overriding product rule: **minimise false positives.** Never show something as established
  (green) or false (red) when it is not; when unsure, be more cautious.

## The rebuild (Oct 25 2026, branch `rebuild`; owner: "build the technical systems first, delete what they replace, audit once at the end")
**Working agreement:** build every system first, delete the hand-made code it replaces, and only then run ONE audit / hypothesis-test
pass and tune settings. No audit after each build, no hand-tweaking, no word lists, no fixes for single cases.
**Built on established libraries** (`requirements-nlp.txt`, installed by `.github/actions/nlp-setup`; HF models cached by actions/cache;
`murmurhash<1.0.14` is pinned because spaCy 3.8 overflows on newer ones): spaCy `en_core_web_lg` (NER + dependency parse), a local
multilingual NLI cross-encoder (mDeBERTa-v3 XNLI) via transformers, sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2`
(stemming TF-IDF fallback), scikit-learn (TF-IDF, agglomerative clustering), networkx, rapidfuzz. All have test backends
(`nli.set_backend`, `nlp.set_backend`, `embed.set_backend`; conftest installs fakes). They cannot run in the sandbox (no Hugging Face):
the real models are first exercised by the end-of-build audit on the runner (`audit` workflow, tool `stack_probe`).
- `idf.py` replaces every stop-word / common-word list (plan, threads, narrative). `reliable.py`: one call layer (failure taxonomy,
  jittered backoff, circuit breaker) under ingest and Tavily; tri-state results (None = could not ask, never cached, never "no").
- `nli.py` replaces the Gemini same / covers / conflict questions (`match.same_facts`, `covers_facts`, `check_conflicts`) and the
  qualifier word lists of `fidelity.py` (a reading must be ENTAILED by its report sentence; a translation is read both ways; polarity.py
  and negation.yaml are gone). `embed.py` + `dupes.py` (topics by clustering, duplicate proposals by similarity) and `disputes.py`
  (same-question gate by similarity, NLI as judge). `split.py` splits compound statements by the dependency parse (`nlp.clauses`) and
  confirms with NLI. `entities.py` + `style.py`: persons come from NER votes, one identity per person; `style.py` holds no list of titles,
  places or bodies (titles come from `config/titles.yaml`). `order.py` + `config/event_stages.yaml`: chronological order by graph.
- **Deleted:** the titles / synonyms / glossary learners, `learning.py`, `context.py`, their `*_learned.yaml` / `devils_advocate.yaml`
  files, the `learn_candidates` table, `learn.sh` and the hourly steps, the entity shadow tool. `relate.py` / `titles.py` / `hindi.py`
  read hand-written files only. Hand-written `synonyms.yaml`, `titles.yaml`, `glossary.yaml` `terms:` stay.
- **Superseded by Rebuild 9-12 below:** B9 (noun chunks), B11 (dossier), B33 (sidebar blocks) and the body-alias lists are built. The real
  "not built" list is the paragraph that begins "Not built (the real list" under Rebuild 14. The Oct 5-24 entries below describe behaviour that
  still holds unless they mention a learner, a qualifier list or a Gemini same / covers / conflict question: those are superseded by this section.
**Rebuild 9-12 (Oct 25 2026, same branch; all real-model / Wikidata paths run only on fakes until the audit):**
`agreement.py` (it/they by dependency parse + lemminflect), `refs.py` (definite phrases by spaCy noun chunks; `HEADS` gone),
`langcheck.py` (LanguageTool, counted not enforced), `bodies.py` (body identity from Wikidata, table `body_links`; `voice.ALIASES` /
`COUNTRY` gone), `blocks.py` (sidebar / link-list filter in ingest), `dossier.py` (per-story trace, table `dossiers`; only the
"statements" and "writer" stages record so far), truth stack: `truth.py` (truth discovery, an extra AND gate in `verify.base_verdicts`),
`groundjudge.py` (evidence gate for false / confirmed), `independence.py` (copy detection lowers outlet counts), `checkworthy.py`
(NLI check-worthiness; None = characterisation), `positions.groups` (interval-based perspective groups), `concepts` by embedding,
`belong._close_lines` prefilter, `threads.find_parents` by embedding + names + NLI (`LINK` thresholds), `events.py` (B15: verb ranks
learned daily from dated claims into `event_ranks`, used by `order.py` for same-day ordering; `act_score` by zero-shot NLI replaces
`news.DECISIVE/PROCESS/DEATHS`; `config/event_stages.yaml` deleted). Everything touching a colour can only make it MORE cautious.
Untuned guesses to read in the audit: `nli.*`, `fidelity.SUPPORT/CONTRA`, `threads.LINK`, `belong.KEEP_SIMILARITY`, `truth.BELIEF_MIN`,
`checkworthy.SURE`, `events.MARGIN/MIN_N/SURE`. The green-line rule (belief replacing the count conjunction) is to be discussed after the build.
Rebuild 12b-13 (same day): `style.Refs.next` chooses pronoun / role / surname by centering (the person still the topic, evidence
for a pronoun, never the same form twice) instead of rotating (B18, partial: the CHAIN / BODY_LEAD regexes remain);
`refs.ask_model` asks only for phrases whose head noun the source writes beside a capitalised word (noun chunks flagged nearly every
"the X": one call per article was too much quota); `dupescore.py` (B16 step 3: logistic regression on the newsroom's own
same-fact answers, tables `pair_labels` + `model_state`, fitted daily, ONLY orders the questions, never merges or skips);
`nameconflict.py` (B17: alias / distinct / disagreement; only structural evidence removes a flag); `factuality.py` (B22: polarity and
certainty from the parse; a "may / might / could" statement is a characterisation in `checkworthy`, never green); `extract._overlap`
(B23: a piece never opens pointing at a paragraph it was not given); `aliases.py` + `EntityTable.link` (B2: "X alias Y" unifies
identities); `inspector.py` (B9: one counted look over the finished text, `narrative.flow.inspector`). Perspectives now need a stored
positions report (`positions.groups`); old tests were updated to feed one. Test stand-ins in `tests/conftest.py` script the NLI
(check-worthiness, decisive acts, one court filing). All paths with real models still untested until the audit.
**Rebuild 14 (Oct 25 2026, same branch; fakes only until the audit):** `attribution.py` (B18: who-said-it read from the dependency
parse: subject, speech verb, adverb, "on Monday", reported clause; replaces `style.CHAIN` / `BODY_LEAD` / `PRON_ATTRIB` / `NEUTRAL`;
a sentence that is more than a plain attribution, or has a quotation, is not read and is left alone); `discourse.py` (B9: introduced
people, centering focus, time cursor per paragraph; counted in `narrative.flow.inspector` as `unintroduced`, `pronoun_without_focus`,
`time_back`, never enforced); `redundancy.py` (B16 4-6: `constrained` union-find with cannot-link used by `consolidate` for the merge
step, `survivor` + `analysis.variants`, `number_pairs` offered to the twice-asked question; strict = merge on two "yes", loose = fold on
one "yes" + `tells`, both already in consolidate); `fellegisunter.py` (unsupervised EM match weight, used by `dupescore.order` while no
labelled model exists; `bands` = size of the middle band); `crosslingual.py` (Devanagari names -> the registry's English spelling before
they enter `EntityTable`, exact lookup only; `compose` puts the registry in scope); `tools/evaluate.py` (THE single audit: claim matching
recall at 99% precision for code / Fellegi-Sunter / logistic, NLI score distribution, inspector counts per article, all untuned thresholds;
one `diagnostics` row kind 'evaluate'; workflow `audit`, tool `evaluate`). The conftest fake parser now builds speech structure.
Not built (the real list, corrected Oct 26): (1) B25/B26/B28-B32 labelled-data evaluation: no owner labels are needed, `tools/evaluate.py` already
measures with the newsroom's own answers; what is missing is running it (audit) and reading the numbers; (2) a coreference model for the writer
(`discourse.py` / `refs.py` / `agreement.py` count dangling pronouns; a fastcoref / coreferee check would be added as a COUNTED metric in the audit
first, never enforced); (3) E1's "re-ask once" (an invalid closed value becomes "unknown"/"attributes" and is counted; build only if the audit shows
the invalid rate matters, it costs quota); (4) E40: `stories.created_at` stays on purpose (`threads.root_of` breaks ties by it; only the unused query
went). DONE Oct 26 (merge audit, runner): `tools/merge_audit.py` showed code's "different" ended pairs the model reads as the same (story 45418: titles, demonyms, accents in names). `relate.fold_latin` (accents off Latin letters), `relate.soft_candidate` (no fact differs: not, figures, dates, clock times; names one-sided after `core_names`), `consolidate._soft_pairs` (embedding cosine >= `SOFT_SIMILARITY` 0.70 (0.85 missed "Amit Shah said 18 were arrested" / "Authorities arrested 18" at 0.81), `SOFT_MAX` 150) offers such pairs to same / covers questions (NLI decides; `tells` ignores title words). `SAME_ASK_MAX` 80 (local reader, no quota). Not yet re-measured on real data. Also: NLI said 'contradiction' 0.98 for 'police and officials seized' / 'revenue team seized' (a lone differing detail): disputes keep code's candidate gate before NLI. DONE Oct 26: S9 graded time field in `fellegisunter` (`time_level`: overlap / one day apart / further / unknown; `times` passed from
`consolidate` through `dupescore.order`); E23 evidence weight per pair in the side table `story_pair_weights` (in `TABLES` of `newsroom.sh`;
`perspectives.pair_means` weights each story by it, a pair stored before counts as 1).
**Rebuild 15-16 (Oct 25 2026, same branch; fakes only until the audit): the NOTES S- and E-lists.** S1 closed factuality fields (polarity,
certainty; `extract._factuality`), S2 central pieces + entity slots for long reports, S3 repeated readings clustered (`_merge_pieces` via
`redundancy`), S4/S6 greedy coverage selection (`selection.greedy`; Tavily failures backed off in `articles.extraction["tavily"]`), S7 blocking
instead of all pairs (`relate.blocks`), S9 soft time (adjacent days: ask, not "different"), S11 NER names, S12 Dawid-Skene gate (`aggregate.py`,
only turns yes into no), S13 QA consistency (`qa.py`), S14 learned contrast words (`contrast.py`), S24/S25 positions with outlet propensity and a
curveball null, S28 themes by agglomerative clustering (`plan._theme_order`), B3 evidence spans (`evidence.py`, `"src"` sentence numbers), B7 places
that differ, B8 text normalisation, B10 mojibake repair + per-sentence language (`hygiene.py`), B20 translation quality estimate (`fidelity.quality_low`).
E-list: E5/E9/E10 dossier log (`dossier.append`: read, consolidate, split, belong), richer `tools/export_story.py`; E11 a verdict set by evidence is
kept ("false" always; "confirmed" unless arithmetic says disputed); E12 the 6-hour clock survives one failing run; E13 no "?" in relation text, first word
lower-cased unless the parse says it starts a name; E14 verify retries wait (`retry_after`) and rotate; E15 a defaulted stance holds "corroborated" at
"developing"; E16 a split must keep every content word (`split._uncovered`), E17 outcomes "piece" / "whole:<rule>" stored and counted in the dossier,
E18 pieces record inherited fields and the relation remap runs in one transaction; E19 "unique to one outlet" only when every same-fact ask was
answered (`analysis.unanswered_asks`); E20 a dateline must name a gazetteer place (`places.is_place`, English and Devanagari), carry a date/agency
tag, or be a capitalised town the report goes on to name; E21 `government` from a closed set (`places.government_name`; else pooled); E22 `checkable` is
kept with the text hash it was judged for (`canonical.rel.checked`) and re-asked when the text changes; E23 pair agreement shrunk by `PRIOR_WEIGHT`;
E24 perspectives use outlets with a fully READ article, and a story keeps `qualifies` for one failing run; E25/E31 the global clusters stay until 3
failing runs (`perspectives._keep_or_clear`, record in `model_state` "global_clusters"); a stale (>48 h) or "why" positions report is unknown, not
"no signal" (E29); positions run BEFORE `recompute_global` in `run.py`; E26 concept mapping remembers failed words (back-off), tries the least-tried
first, compares by stem; E27 one `GENERIC_AUTHOR` (origins); E28 positions use explicit stances only, per (statement, article), denial wins;
E30 positions report gains per-outlet answer rate and corr(theta, rate); E32-E34 belong: first listed tag word read, unparsed counted, answers kept
as forward/reverse per (line, hash of the NEWS block), topics joined whole by union-find, order independent; E35 `dupes.topics` keeps every id
(duplicate texts); E36 belong counts + `LEADUP_DAYS` as parameter in the dossier; E37 `find_parents` returns stored parents when scoring fails;
E38 `save_links` keeps twins on other pages, one transaction; E39 thread check keyed by headline + candidate set; E41 `story_links.reason` is JSON with
the edge type, `root_of` breaks ties by creation time. Test suite green except the known hash-seed flake in `test_end_to_end` (set order upstream).
Untuned: `PRIOR_WEIGHT`, `positions.MAX_AGE_HOURS`, `perspectives.CLEAR_AFTER`, `fidelity.QE_MIN`, `qa.MIN_SCORE`, `contrast.MIN_PAIRS/RATIO`,
`relate.BLOCK_*`, `aggregate.PRIOR/POSTERIOR_MIN`.
**Next:** merge `rebuild` to main only when the owner agrees; run the single audit pass (stack_probe, audit, story_check), read the
NLI thresholds (`nli.ENTAIL/CONTRA/UNSURE`, `fidelity.SUPPORT/CONTRA`), the clause splitter and the NER-based speaker keys on real
stories, and tune settings then.

## Hard constraints
- Free tiers only. **No billing**, ever. Gemini free API (3 keys: `GEMINI_API_KEY`, `_2`, `_3`,
  separate projects; the owner decided this), Tavily free (1,000 credits/month, ≤31/day), Supabase free
  (stay well under 500 MB), GitHub Actions on a public repo.
- The pipeline's DB role (`nishpaksh_app`) cannot create or alter tables: schema changes go in
  `supabase/migrations/*.sql` and are applied with the Supabase MCP (`apply_migration`), with RLS policy
  `app_full_access` and grants for `nishpaksh_app`. The site reads `published` with the anon key.
- Destructive SQL through MCP needs the owner's approval (he may be away); prefer non-destructive steps.

## Decisions (do not undo without discussing)
- **Green (established):** 3+ independent outlets actually read (owner groups and wire copies merged,
  `config/ownership.yaml`), 2+ **independent origins** (`origins.py`: named sources; officials of one
  government = one origin; an outlet's own voice counts only as original reporting; unattributed /
  unnamed = pool, never counts), no denial, a checkable fact (not a characterisation), standing 6 h
  from when the rule was first met (before that: "developing", dotted teal).
- Brown = not yet cross-checked (owner, Oct 9 2026: teal for developing and clay brown for unchecked, so
  neither is grey and the two cannot be confused; the colour bar has a teal segment of its own); amber = sources disagree; red with a FALSE tag = primary evidence
  (FIR, court record, official data, video) shows it false, two model families agreeing.
  **Purple = one outlet only (owner, Oct 7 2026):** a statement only one independent outlet reports
  (and not disputed or false) goes INTO the article, shown purple ("one outlet only": an exclusive,
  or a mistake); the colour, not words, says so (see "One author's voice"). `narrative.shade`; the writer and the revision pass must
  use every statement, one-outlet lines included (they were "minor" and optional before).
- **Category names (owner, Oct 22 2026).** One wording everywhere a reader or the voice guide sees it: purple `single` = "Single source" (HI "एक ही स्रोत"), clay brown `unverified` = "Not confirmed" (HI "अपुष्ट"; the site does not verify anything, so "unverified" and "not yet cross-checked" are retired). "Source" means an independent origin of information (owner groups and wire copies merged), never an article. The two are NOT the same category: `single` = one independent source; `unverified` = anything short of the confirmed rule (2 sources, one origin repeated, not checkable). Internal keys, CSS classes and the writer's own labels (`narrative.STATUS_LABEL`: ONE OUTLET ONLY / REPORTED) are unchanged, so no page is rewritten; `sw.js` np-main-67.
- **Interim publishing rule** while perspectives are unknown: 3+ independent read outlets (state media
  and PIB not counted, see "Outlets outside India") and 2+ origins. Perspectives emerge from agreement data (no hand labels of outlets).
- **Option B:** a page we could not read (headline/blurb only) is listed as "could not be read",
  never used for facts. Tavily reads blocked pages on budget.
- **One author's voice; the colour carries the support (owner, Oct 7 2026, option A).** No "according
  to reports", "reportedly", "reports said", "one report said" anywhere: the article reads as one author
  writing for a reader, and the colour key sits between the headline and the article (site). Kept in
  words only what colour cannot carry: a named speaker's claim ("police said"), "allegedly" where the
  outlets use it, and a dispute's two versions and whose. Code removes hedge words
  (`narrative._one_hedge`, not in disputes) and no longer adds a paragraph hedge. House style by code
  (`style.py`, after the spelling pass): a person's full name and title once, then the surname (not
  when two names share it; only with evidence it is a person: a title or role before it, a speech verb
  after it, or a speaker), and "He said ... He added ..." runs become "..., he said."
- **Writing:** no outlet names in the text (source numbers carry them); claims pinned on whoever makes
  them; no hedge words (above); "after" is fine, cause words only if a statement has them;
  never invent a speaker; "allegedly" stays as long as the outlets say it. Suicide stories get the
  Tele-MANAS helpline note.
- **Only the writer produces prose (Oct 2026).** A new story is published only with a good essay
  (`narrative.essay_ok`); otherwise it waits. Writer order (models.yaml): every Flash model, best
  first, then **3.5 Flash-Lite as the last resort** (owner, Oct 6 2026, after Flash refused on all keys
  for a day; it keeps 300/day per key for reading). Code-stitched pages and older Flash-Lite essays
  are never kept (`compose._keepable`, `WRITER_LITE_OK`). Rejected sentences are dropped, not
  patched. A fallback headline never goes live. Writer failures per statement set are kept in
  `stories.analysis.writer_failures` (3 tries max).
- **Editions: written once, like a newspaper (owner, Oct 5 2026; `editions.py`).**
  - An article is written when coverage has SETTLED: publishing rule met, then no new independent
    outlet for 3 h, or 8 h after the rule was first met (`analysis.edition.met_at`). On Oct 1-5 data a
    3 h wait saw 86% of a story's outlets. A story whose newest source is >36 h old is not written.
  - A published article is CLOSED: text, headline, statements, sections, perspectives never change;
    no article joins it, nothing is read or analysed for it, no model call is spent on it. Only its
    colours mature by code (`editions.mature`: the 6-hour clock on the evidence it was written with).
    The parent is never corrected: a follow-up carries any dispute.
  - Later reports of a published event go to a CANDIDATE story (`stories.py` redirects joins;
    `analysis.edition.follows`). It is read like any story and published only as a follow-up when,
    against its parent (`follow_up_ok`, one Flash-Lite call per statement set): 4+ new non-minor core
    statements (or half the parent's) carried by 3+ independent outlets, or a MAJOR development
    (arrest, FIR/charges, court order/verdict/bail, deaths, resignation/sacking, official decision,
    result) carried by 3+. No per-day limit (owner, Oct 10 2026: it was 5+ major-only on the parent's IST date): the same bar holds all day. The desk (`desk.ready`) writes stories whose topic has NO article published today first (`fresh_topics`, topic = root of the story_links / `edition.follows` chain), then the rest by importance, so a topic already covered today is never held back, only queued behind new topics.
  - After 3 days the article moves to the `archive` branch (`pagearchive.py`, step in hourly.yml:
    `pages/<id>.json.gz`, `index/<YYYY-MM>.jsonl`) and is deleted from Supabase only after the push.
    The site and follow-ups read archived parents from the branch (raw.githubusercontent.com).
- **Titles of later mentions are cut whole (owner, Oct 12 2026).** `style.shorten_names` used a regex that took any run of
  title words in front of a name, so for a repeated "Lok Sabha Leader of Opposition Rahul Gandhi" it cut "Opposition Rahul"
  and left "Lok Sabha Leader of Gandhi" (also "Chief Justice of Kant"; only on later mentions, which is why it was
  intermittent). It now asks `titles.title_start`, the one phrase finder (`title_before` uses it too): "of" and "the" bridge
  title words, capitalised qualifiers ("Lok Sabha") join, a clause end stops it, and the title goes whole or not at all.
  The introduction stays as written. Site: the colour key under the headline is now in the bar's order (established,
  developing, partial, one outlet, disputed, false, not cross-checked).
- **Aim 85%, publish from 80% (owner, Oct 12 2026).** The writer is still told to carry 85% of every statement
  (`narrative.COMPLETE`: prompts and fill passes work towards it), but the final check (`essay_ok`, `essay_shortfall`)
  requires only `narrative.PUBLISH_MIN` = 80%. Stories were refused for missing one or two statements of the aim. Under
  80% nothing changes: the draft is kept and continued on the next try.
- **Writing desk and preparation queue (owner, Oct 6 2026).** Target: at least one article an hour,
  at most two. The writer is its own step (`desk.py`; since Oct 10 2026 in hourly.yml right after the
  pipeline, which starts :05 UTC = :35 IST; before, workflow `writer.yml` at :45 UTC): it writes the
  settled stories most important first until the clock hour has `desk_per_hour` (2) articles; a try
  (`desk_tries`, 5) counts only when the writer is asked; stories turned away before that (a follow-up
  refused, no headline) are counted in `skipped` and the desk moves on (at most 25 looked at), and a
  refused follow-up is not looked at again until a new outlet joins (Oct 7 2026: three refused
  candidates used all five tries two runs in a row and nothing was written). A failed headline no
  longer stops a story before writing: the article is written, the headline written from its lead, and
  if that fails too the finished article waits as a kept draft (outcome "headline failed"). Models that
  refused on every key in the previous desk run (within 75 min, `router.dropped`, logged as `dropped`)
  are skipped for one run (`desk.refused_last_run`, logged as `skipping`), so every other run tries
  Flash again (Oct 7 2026: ~15 refused Flash calls per run before Flash-Lite wrote); it logs
  to `diagnostics` (kind 'desk'), never `runs` (the gate spaces pipeline runs by `runs`). The pipeline
  (:05) only prepares: every story with 3+ independent sources is rated from its HEADLINES
  (`priority.rank_new`, one Flash-Lite call per 20 stories, importance rubric 1-5 + filler), and only
  the best `prep_queue` (16) are read, analysed, Tavily-read and searched first (`priority.queue`);
  the rest wait as headlines and enter when they rank higher (re-rated when coverage grows by 2+).
  Oct 6 before this: 458 articles read in 95 stories in 8 h for 8 published (~160 Flash-Lite calls
  per article). 3.5 Flash-Lite is the writer's first claim: reading stops at 250 left, analysis at 120,
  page at 80 (models.yaml `keep`); writer calls try up to 16 times so they reach it. Quota usage is
  saved as increments (`Store.quota_add`), since both jobs share the keys.
- **Grammar, not rules (owner, Oct 10 2026; direction agreed, built in phases).** Prohibitions added after each failure
  fail more than half the time with the small models, and a failed sentence is dropped, so more checks can lower the
  publish rate. Direction: CONSTRAIN WHAT THE WRITER IS GIVEN (code owns names, paragraph plan, sentence shapes; the
  model only phrases) rather than only checking what it wrote. Two independent grammars: (1) by statement status
  (established / developing / unchecked / one outlet / disputed / false: allowed sentence shapes and markers per
  status), (2) by article structure: article > sections > paragraphs > paragraph links > sentences > words (titles
  and names included). Only words, names and sentence shapes are checkable by code; "flow" is not a rule, it comes from
  a sound paragraph plan (one subject per paragraph, set order).
  **Phase 1, done: titles registry** (`config/titles.yaml`, `titles.py`): one list of honorifics and roles with
  synonyms (`CJI` = `Chief Justice of India`), kinds (`is_a`: a CJI is a Supreme Court judge, never the same) and
  conditions (`requires_any`: "Chief Justice" alone is the CJI only in a Supreme Court / India text). `style.py`,
  `people.py`, `voice.py` take their title words from it (they used to keep three private lists). `style.shorten_names`
  now owns every mention by code: the FIRST mention is the full introduction (title + full name, the title taken from
  the statements), a bare surname or "Title Surname" before that is expanded to it, every LATER mention is the surname
  alone, whatever the writer wrote; full names come from the statements too, not only from the article text.
  **Phase 2, done (owner: "yes let's build", Oct 10 2026): grammar by statement status** (`grammar.py`, no model in it).
  One table `STATUS` (established / developing / unverified = not cross-checked / single = one outlet / disputed /
  false): what the colour already says, what the words may carry (the four plain statuses: plain declarative,
  attribution only for the statement's own named speaker; disputed: both versions each with its holder; false: the
  claim, who made it, what the evidence shows) and the markers required. The marker lists (`FALSE_MARKERS`,
  `DISPUTE_MARKERS`, `ATTRIBUTION_VERBS`, `HEDGE_MARKERS`) and `CONNECTIVE` moved there; `narrative.py` re-exports them
  (`recap.py` imports them). Three uses: (1) GIVEN to the writer: `_statement_line` adds `| SHAPE: ...` to a statement
  that is not plain (`grammar.shape_line`: "<content>, X said.", the statement's own act verb, the false-claim form
  with its evidence, the two-version form); a plain statement gets nothing; both prompts say a SHAPE is the form to
  use. (2) APPLIED by code: when a sentence fails a check and the fault has ONE safe fix, `narrative._check_one` applies
  `grammar.repair` and runs EVERY check again; the repair is kept only if the sentence then passes, otherwise the original
  failure stands (a repair can turn a dropped sentence into a published one that passes, never relax a check). Repairs:
  `not a full sentence` -> add the full stop (never on a fragment: a joining word first, cut off on one, or under 4
  words); `claim without its speaker` -> ", X said." after the claim (one speaker, no other speaker among the
  statements, and the sentence has no speech verb of its own: a wrongly attributed sentence is not given a second
  speaker; for a false claim it goes before the evidence); `false without saying so` -> "The evidence shows this is false:
  <the statement's evidence>." (only when the false claim is the sentence's only statement); `verb the statements do
  not use` -> "said that" for claimed/insisted/warned/threatened/conceded/admitted/confessed/vowed that, NEVER for a verb that
  negates (denied/refused/rejected/dismissed that); `pronoun without evidence` -> the speaker's name for "He/She said"
  (the names pass writes it as full name or surname). A repaired sentence loses its colour parts (one colour, the
  weakest). The counters show it: a repaired fault is counted as `fixed: <reason>` in `reject_reasons` /
  `first_draft_reasons`, not as a rejection (read them with `tools/replay.py`: a high `fixed:` count means the writer
  keeps making that fault and the prompt shape is still not holding). (3) one new check: `empty set-up` ("X set out his
  position.": cites a statement, says nothing of it; short, no figure) is refused so the fill pass writes the statement.
  `WRITER_VERSION` was NOT raised: old pages keep their text (a raise rewrites every page once, a quota cost); new and
  rewritten pages get the shapes and repairs. Not run on real stories (no data in the repo); the unit tests ran as plain
  Python (the sandbox had no pytest / sqlalchemy), see `tests/test_pipeline.py` (grammar tests at the end).
  **Phase 3, done (owner: "continue and build the next phase", Oct 10 2026): the paragraph plan in code** (`plan.py`, no
  model in it). The writer used to receive every statement sorted into sections and decide the paragraphs itself; code
  regrouped afterwards. Now code decides, the writer phrases. (1) `plan.build(items, sec)`: article > sections >
  paragraphs, each section with its own rule (`plan.RULES`: how its statements are ordered, what makes a paragraph, how
  it opens). news = one paragraph (the lead, chosen by `news.py`); background / happened / next in TIME order;
  explained and numbers in the order given; related one paragraph per `related_event` label; say = one paragraph per
  speaker (`_by_speaker`: speakers in order of first appearance, an answer right after what it answers, a long argument
  cut by subject). A statement and its contradiction / response / updated figure are one unit (`_links`, never split). A
  paragraph takes at most 4 statements (`MAX_STATEMENTS`) and changes subject (no shared name or key word with it) only
  after 2 (`MIN_STATEMENTS`): a paragraph of one statement takes the next whatever it is about, a lone last statement
  joins the one before (story 13792: seven one-sentence paragraphs). Each paragraph also carries HOW IT OPENS (the
  link to the paragraph before, `plan._open`): its time when the time changes ("opens with its time (5 October)"), its
  speaker, "the one who answers (X), saying what is answered (#6)", "the same speaker as the paragraph before: do not
  introduce them again", "the thing being explained, then what it means". (2) GIVEN to the writer: `plan.block` replaces
  `_section_block` in `WRITER_PROMPT` (SECTION, then PARAGRAPH n with how it opens, then its statements; the prompt says
  write exactly one paragraph per PARAGRAPH, from only its statements); the fill prompt tags each statement
  `| paragraph: n`. (3) APPLIED by code after writing and the coherence rewrite: `plan.conform` puts every sentence
  back into the paragraph most of its statements were planned in (a tie: the section the writer used, then the
  earlier one), paragraphs in plan order, sentences in the statements' own order inside a paragraph; a sentence leaning
  on the one before ("He added ...", `LEANS_BACK`) goes where that one went, so a paragraph never opens with it; a lead
  sentence citing a news statement stays the lead; when no news was chosen the writer's own "news" paragraph stays. A
  sentence is never changed or lost. The news fallback ("first What happened paragraph becomes the lead") now runs
  after `conform`. `shape_paragraphs(join=False)` when a plan exists (it only cuts a paragraph over 6 sentences; it used
  to join neighbouring short ones regardless of subject). Stats in the article's `narrative.plan`:
  `{planned, written, moved, orphans}` (`moved` = sentences the writer put in another section than the plan's; a high
  number means the prompt is still not holding, read it with `tools/replay.py`). No new model call: the plan is in the
  same draft and fill prompts, so the free-tier call count is unchanged. `WRITER_VERSION` not raised (old pages keep
  their text). NOT RUN ON REAL STORIES (no data in the repo, no pytest / sqlalchemy in the sandbox): the unit tests
  and 6 new plan tests ran as plain Python; the 72 database-backed tests did not run.
  **Phase 4, done (owner: "continue from here and build the next phase", Oct 10 2026): sentence grammar** (`sentences.py`,
  no model in it): what is inside a paragraph, same direction (GIVE the writer the connection, APPLY safe fixes by code, never
  a new prohibition that drops a sentence). (1) GIVEN: `sentences.link_line(item, previous)` adds `| LINK: ...` to each
  statement after the first of its paragraph (`plan.block(..., link=)`, and the fill prompt, using the plan's previous
  statement): "contrast with #p: both versions in ONE sentence", "the answer to #p", "same speaker as #p: one \"said\" carries
  both points, or end with \", X said.\"; do not begin with the name again", "later than #p (time)", "same subject as #p: refer
  back to it, do not repeat its full name"; nothing for a statement that starts a new point. Both prompts explain LINK and tell
  the writer never to open with Furthermore / Moreover / Additionally / Notably. (2) APPLIED after `shape_paragraphs`
  (`sentences.polish`): `strip_filler` takes off an empty opening word (Furthermore, Moreover, Additionally, In addition,
  Notably, Importantly, Interestingly, "It is worth noting that"; NOT However / Meanwhile / Then, which say contrast or time);
  `split_stacked` makes "A; B" two sentences when it cites 2+ statements and is long (over 30 words, or 3+ statements): only
  with exactly one ";", no parts, no quotation, no dispute and no partner (contradiction, response, updated figure) among
  its ids, a second half that does not lean on the first, every statement clearly nearer one half (shared words; a tie =
  no split) and each half passing on its own. EVERY change goes through `narrative._still_ok` = all the checks of
  `_check_one` (without repair, counters left untouched) and is kept only if the sentence passes; otherwise the writer's
  sentence stays. (`style.vary_attribution` still owns runs of one speaker's attributions: not duplicated.) (3) COUNTED, not
  enforced (`sentences.stats`): `alike` (two sentences in a row opening with the same two words), `long` (past 45 words),
  `unlinked` (nothing links a sentence to the one before: no shared subject / speaker, no leaning pronoun, no time or contrast
  opening, no partner), `joins`; with `filler` and `split` (changes kept) they are the article's `narrative.flow`. Read them
  with the `fixed:` counts (phase 2) and `narrative.plan.moved` (phase 3): a high `unlinked` or `alike` says the LINK lines
  are not holding. No new model call. `WRITER_VERSION` not raised. NOT RUN ON REAL STORIES: 6 new tests ran as plain Python
  (db and stemmer stubbed, no pytest / sqlalchemy in the sandbox); on the same harness the original code passes 78 and this
  passes 84, with the same 12 environment failures (router / pytest.approx, db, stemmer stub); the 72 database-backed tests
  did not run. `narrative.flow` is not yet printed by `tools/replay.py`.
  **Titles learned from the outlets, done (owner: "I want the titles list saved on GitHub, learned titles appended to that
  document", Oct 10 2026)** (`learn.py`, `config/titles_learned.yaml`, `.github/scripts/learn_titles.sh`; no model). The
  hand-written `config/titles.yaml` cannot hold every title, so the job appends the ones the news shows. A word is learned
  only on counting: it stands in the MIDDLE of a sentence (after a lower-case word; sentence openers like "Yesterday" are
  out) directly before the full name of a person statements are attributed to (`claims.attributed_to`, bodies out), in 2+
  independent groups of outlets (`wire.independence_groups`) and 2+ outlets, before 2+ different people, and the same word
  also appears in lower case in the articles 2+ times (a common noun, not a place, party or company); known titles,
  honorifics, openers and the person's own name words are skipped; at most 20 new entries a run. The entry is one line
  `{id: learned_<word>, forms: [Word], ref: the <word>, learned: <date>, seen: [up to 3 names]}`, only ever APPENDED
  (`learn.append`, text append, header kept). `titles._data` reads it after the hand-written file (the hand-written entry
  wins by id and by form; a missing, broken or malformed file adds nothing and never stops the job), so every module that asks
  `titles` (names pass, people, voice) knows the title from the next run on. The job step "Learn titles from the outlets" in
  `hourly.yml` (after the desk, before saving the newsroom, `continue-on-error`) runs `learn_titles.sh`: pull the branch,
  `python -m nishpaksh.learn`, commit ONLY `config/titles_learned.yaml`, push to the branch the job runs on with the job's
  token (`contents: write` was already there); a push by that token starts no other workflow; if the branch is protected
  the push fails harmlessly and the hour goes on. A WRONG ENTRY: delete its line and put its word in `rejected:` at the
  top of the file (`learn.rejected`), so it is never learned again. The hand-written list already holds most roles
  (Captain, Chancellor, Coach, Inspector ...), so expect few entries at first. Dates are kept because people change
  office; no claim about who holds which office is stored. Run by hand: `python -m nishpaksh.learn --dry-run`. NOT RUN ON
  REAL DATA: 5 new tests ran as plain Python (89 pass on the stubbed harness, the same 12 environment failures); the
  database read in `learn.run` and the git step have not run.
  Not yet built (next, in this order): MEASURE on stored data (`tools/replay.py`: `fixed:` counts, `plan.moved`, `flow`) and
  tune the phase 2-4 rules against what really fails; a words-level pass (house vocabulary, the same thing named the same
  way across sentences). The titles' dates are recorded but not yet used to drop a title after an office changes hands.
- **Every sentence knows what came before it (owner, Oct 15 2026; `refs.py`).** Seen: lead "It was trying to trace the missing
  video recording, Election Commission of India said." and "The new scheme is replacing the Mahatma Gandhi ... Scheme." Causes:
  (1) reading rule 2b moves "said" + speaker out of the fact, so a speaker-subject became "It"; a sentence that pointed back to an
  earlier sentence of its article ("the new scheme") lost its target; the prompt asked for names (2c) but nothing checked;
  (2) the writer reorders statements, so even a good sentence dangles when the plan puts it first; `gloss.py` knew kin and offices
  only; (3) nothing checked how a paragraph OPENS. Fix in three layers, code first: A `refs.resolve_extraction` (in `extract`, with the
  source article): a subject pronoun is replaced by the speaker ONLY when the source writes "<speaker> said it was ..."; a generic
  thing (`refs.HEADS`: scheme, bill, video ...) gets the name the source gives it, stored in `claims.rel.refs` (never in the
  text: matching compares texts; `compose._item_refs` merges them onto the statement); what code cannot find is asked ONCE per
  article in one batched call (`refs.ask_model`) and kept only if the answer's words stand in the source; two candidate names =
  none. B `refs.gloss_article` (in `style.polish`, last): first written mention of a thing the headline and earlier text did not
  name gets the name in brackets, once (square brackets when the name has round ones). C `refs.opening_problem` in
  `narrative._check_one` (`opens=` first sentence of a paragraph): It/They/This/These/Those/Its/Their refused as "opens with a
  pronoun"; repair `grammar._opening`: "It was ..., X said." -> "X said it was ...". Counted: `narrative.refs`
  {glossed, unresolved} (read with replay). Not built: pronoun/definite references INSIDE a paragraph (only openers are checked),
  Hindi pages, a re-read of already stored statements (old claims have no `refs`; they apply from the next reading).
  **Follow-up, same day (owner: mid-paragraph pronouns, Hindi, and "they" for a court).** (1) Mid-paragraph:
  `refs.antecedent_problem` in `narrative._check_one` (runs FIRST, before the validator, so its repair also cures the speaker
  faults the validator would name): an It / They / Its / Their with no name or "the + noun" before it in the sentence or in `near` (the
  sentence before + the speaker in scope) is refused as "pronoun without antecedent"; repair `grammar._pronoun` now also names the
  speaker for "It / They added that ..." when the speaker is a body. `_still_ok` passes `near=None` (position unknown: not asked).
  Narrow on purpose: any name counts as something to point at; what it cannot see is a wrong antecedent. (2) Hindi: a Hindi SOURCE is
  matched across scripts (`refs.is_hindi`, `_like_in_hindi` over `textmatch._roman/_like`): a gloss must be English letters and
  every name word / figure must have a Devanagari word it can be; code does not search a Hindi source (pronoun left open and counted),
  the batched question asks for the name "in English letters" (`ASK_PROMPT_HI`). The Hindi PAGE is a per-sentence translation of the
  finished English, so English fixes carry over; `compose.translation_problem` now rejects a translation that changes or drops a
  bracketed name ("bracketed name changed") or opens with a Hindi pronoun when the English has none ("pronoun added"); the prompt
  says brackets are copied and a court/commission/board/police takes the plural (वे, उन्होंने). (3) Collective-noun agreement
  (notional concord): `agreement.py` + `config/collectives.yaml` (court, bench, tribunal, commission, committee, council, cabinet,
  board, panel, jury, parliament, assembly, police ...; government, ministry, party, company stay "it" until added there):
  `it / its / itself` whose NEAREST body is such a body (same clause; a person is no body; expletive "it is clear that" left) become
  they / their / themselves, with the verb (was-were, is-are, has-have, says-say), in `style.polish` after `vary_attribution`;
  `voice.body_refs` gives "they" for them; the writer prompt says so; counted as `narrative.plural_bodies`. Not done: an object
  "it" after other verbs, "it's", a body named only by a pronoun with no body in the sentence or the one before.
- **Story layers (Oct 5 2026, owner):** a story has its own event (core) and CONTEXT: background,
  related events (a separate event the reports connect to this one: written as separate, never
  blended), explanation, reactions, what next. Extraction records context (`claims.rel.context`),
  consolidation can re-label statements (`analysis.roles`). Headline, timeline and essay_ok use the
  core only; context is written after it and coloured like everything else.
- **Disputes: one gate (owner, Oct 7 2026; `disputes.py`).** Replaced nine paths (frames adding
  contradictions on arrival and deciding them in review with no check, the one-shot "contradict" question,
  `real_difference` / `typed_difference`, the model's own list, "same" lines with different numbers): "17 of
  the 19 crew are Indian" / "11 of the 12 injured are Indian" was shown amber. A dispute is the SAME
  QUESTION with a DIFFERENT ANSWER. (1) Code (`disputes.candidate`): the speaker taken off ("Police said",
  "according to"), the answer taken out (numbers, number words, dates, weekdays, "not"); what remains
  must be nearly the same words (with `relate.SYNONYM`) and the same names; rounding, bounds ("at least"),
  and "X of Y" with different totals are cleared by code. Proposals (the consolidation model, the frames,
  earlier marks) pass the same gate. (2) Figures over time: when every report of one figure was
  published at least 1 h after every report of the other, it is an UPDATE (`analysis.updates`, old ->
  new), not a dispute: written together, the newest first, the older mentioned; each keeps its colour.
  (3) `match.check_conflicts` asked twice, A/B swapped: two "cannot both be true" = amber (however many
  outlets on each side; an official against an outlet is a dispute too); any "unsure", the answers
  disagreeing, or not yet asked = doubtful (`analysis.doubtful_conflicts`: no amber, no green). Answers
  cached per ordered pair in `analysis.conflict_checks`. Claim/response pairs are never disputes. Only
  the story review makes disputes; arrival (`match.match_story`) only joins plainly identical wording.
  Outlet denials (a report that denies a claim, `verify.py`) are a separate relation, unchanged. The
  writer puts a real dispute with its subject, never in a closing "accounts differ" paragraph.
- **Frames: statements compared field by field (owner, Oct 6 2026; `frames.py`).** Reading gives every
  statement who / action (base verb) / what / value / where / negated; words are reduced to roots
  (Snowball stemmer), numbers read as numbers (crore, million, "at least", "about"). Code compares:
  same slot (who, action, what) + agreeing values = one fact (merged); same slot + incompatible values
  or negation = contradiction (the ONLY way to one between statements with frames); a missing value =
  compatible (never a dispute, wording decides merging); same slot at different times = unsure;
  anything else = different. Frames now only PROPOSE, for merging and for disputes; they decide
  nothing (see "One structure for the same fact" and "Disputes: one gate"). A day-precision date covers the whole day (`_times_apart`). Dates are read as dates ("6 December 1986" = "1986-12-06"; a year agrees
  with a full date in it), and a dispute needs the same object: a capitalised word in one name the other
  lacks makes two things ("Param Vishisht Seva Medal" / "Vishisht Seva Medal": different, Oct 7 2026). Model "contradict"/"same" judgements count only for statements read
  before frames (those still go through `check_conflicts`). Stored in `claims.rel.frame` and
  `canonical.rel.frame`.
- **One structure for the same fact (owner, Oct 7 2026; `relate.py`).** Replaced the veto chain
  (frames vetoing identical text, `may_be_same`, the NUM veto, frame auto-merges): two identical lines
  from two outlets stayed two statements because two readings labelled them differently. The words
  outrank the labels. `relate.relate(a, b)` decides by code on numbers (as numbers, ordinals, "eleven"),
  names (capitalised words; the names both lines share are left out of the word overlap) and root words:
  same / a covers b / ask / ask-covers / different; one negated and one not, or different times, is
  always different BY CODE (a pair the topic step proposes is still asked: see "The same fact in other words"). Code merges only "same"; "ask" goes to `match.same_facts` (asked twice, A/B swapped)
  and "ask-covers" to `match.covers_facts` (asked twice, reversed order); a short synonym list
  (`relate.SYNONYM`: injured/hurt/wounded, arrested/detained, part/section...; never injured/killed)
  is read as one word; proposals from the
  consolidation model and the frames go through the same question. A detailed line COVERS a short one
  when it has every number, name and nearly every word of it (code alone only when it adds no number
  and no word like "another", "earlier"; else the model is asked): the short line is not merged (its
  outlets would lend support to details they never reported) but kept as covered
  (`analysis.covered`), folded into the detailed line by `compose.fold_covered` (its outlets listed as
  sources, the detailed line's colour unchanged). Last net: `narrative._drop_repeats` drops a written
  sentence that an earlier one already says (its ids join the earlier one; a colour can only get
  weaker; a later sentence in the same paragraph that says all of an earlier one and more replaces it).
  Both `match.py` (arrival: code "same" only) and `consolidate.py` use it. Disputes are a separate,
  later step (frames still propose contradictions).
- **A figure is one figure however it is written (owner, Oct 11 2026; `figures.py`; story seen: "twenty six", "twenty-six"
  and "26" in one sentence).** Four places read numbers on their own and none read a spelled number as a whole:
  `relate.Profile` made "twenty-six" the figures 20 and 6, so "26 were killed" and "twenty-six were killed" were two facts
  (never merged, offered as a possible dispute) and the writer printed all three spellings; the validator
  (`narrative._numbers`) read digits only, so a wrong spelled figure ("twenty-seven" for 26) passed unchecked; `recap` and
  `frames` each had their own table. Now ONE reader, `figures.find/values/value_set`: digits (Indian grouping 1,00,000,
  decimals, Devanagari ०-९), scales (lakh, crore, million, billion, cr, mn, k, "25 basis points" = 0.25), digit ordinals
  (29th), spelled numbers with compounds ("twenty-six", "one hundred and five", "two lakh fifty thousand", "twelve
  thousand crore", "a dozen"), roman numerals ONLY after a label word and only I/V/X to 39 ("Section IV", "Phase II",
  "World War II", "Class X"; "Group C/D" are labels, not 100/500). Not figures: "twenty-sixth", "two-thirds", spoken
  years, first/second, half/once. **IDENTIFY ONLY, NEVER REWRITE (owner): an outlet may have meant words, digits or
  roman, so no text is changed and there is no house spelling; texts are compared by VALUE and printed as written.**
  Used by `frames.numbers` (so `relate`, `split`, `disputes`), `relate.Profile` (number words also leave the root words,
  so "twenty-six crore" and "26 crore" have the same words), `narrative._numbers` (the writer's sentence is checked against
  its statements by value; a written spelled number below `figures.SPOKEN_MIN` = 2 is not checked, "no one" / "one of"
  are not figures, but "two" may not appear unless the statements have 2: NEW, may drop a few sentences that really carry a
  wrong spelled figure), `_is_figure` ("By the numbers" now also takes spelled figures), `recap._nums`, the headline check
  (`news`), `grammar.empty_setup`, and the omission check (`textmatch`: a figure is found by value in the outlet's text).
  Not done: Hindi number words (the statements are English; Devanagari DIGITS are read). Tests: `tests/test_figures.py`
  (needs no database). Not run on real stories; the database-backed tests did not run (no sqlalchemy / pytest in the sandbox).
- **One fact per statement (owner, Oct 8 2026; `split.py`, story 13970).** "The repo rate is the rate at which
  the RBI lends to banks" was written three times, the rate decision four: outlets write compound sentences
  (A = shared fact + x, B = shared fact + y), neither covers the other, so the shared fact stayed in two
  statements. Before matching, in preparation, a fact row that looks compound (14+ words and a joining
  "and", ", which", ";", " but "...) is split into its single facts by one Flash-Lite question per batch of 10
  (analysis tier since Oct 9): at most 3, 4 allowed, more = kept whole; one fact = unchanged. Code checks every piece: its
  numbers and names from the original, nearly all its words too, the pieces together carry every number and
  name, a said thing keeps its speaker in every piece, a "not" is never lost or added, and no two pieces share 60%+
  of their root words (a list split apart: "higher EMIs for home loans" / "... for car loans", seen on 13970);
  any failure keeps the row whole. Pieces replace the row (same article, stance, speaker, evidence, time, context role; loaded words
  on the first piece; no frame; a relation naming the row names its first piece), marked `rel.split`
  ("piece"; checked rows "whole") so a row is asked once, and go through matching like any fact. Numbers:
  "25 basis points" reads as 0.25 per cent (`frames.numbers`). Writing: a sentence may now have up to THREE
  coloured parts (`narrative.MAX_PARTS`). `replay --mode split` shows a stored story's statements after.
- **The same fact in other words, found by topic (owner, Oct 8 2026; `dupes.py`, story 13970 after the split:
  "rate cuts were off the table" / "no option for interest rate cuts"; "by 0.25 percent" / "by 25 basis points to
  5.50 per cent").** Deciding was never the weak part; finding the pairs was (the review's seven-job call over 90
  statements found five). Now, in the review: one call sorts the statements into topics (a paragraph's subject),
  then per topic (up to 12) one call proposes "same" pairs and "covers" pairs (longer first). PROPOSALS ONLY: a
  same pair goes through the existing gate (relate by code, then `same_facts` asked twice); a covers pair must
  keep the short line's numbers and its "not" (code), then `covers_facts` asked twice. Topics and answers kept by
  TEXT in `stories.analysis.dupe_checks` (ids change after merges). `CONSOLIDATE_VERSION` 9: every unpublished
  story is reviewed once more. A "no" does not keep a proposed pair apart (owner, Oct 8 2026: "if they mean the
  same thing, we should not leave them unmerged because one has no in it"): a pair the topic step proposed is
  asked even when one side is negated, and the twice-asked same question decides; its examples hold the trap
  ("Police arrested him" / "did not arrest him" -> different; "rate cuts are off the table" / "no option for
  rate cuts" -> same). Numbers must still agree. Code alone still never merges a negated and a plain line.
- **Write facts, cite outlets (owner, Oct 9 2026).** "It's fine if we leave out lines from outlets if they have
  already been covered from other outlets and just give their number." The article tells each FACT once:
  completeness (`essay_ok`, 85%) counts facts, not statements. A line whose fact another line already tells is
  FOLDED (`analysis.covered` -> `compose.fold_covered`): not written, its outlets' numbers go on the telling
  line's sentence, which keeps its OWN colour (never raised by them). Folding needs ONE model "yes" (same fact,
  or the line says everything the other does: the first answer of the existing twice-asked questions, recorded
  as "f..." in `same_checks`) plus code: every number and name of the folded line is in the telling line
  (`consolidate.tells`); the telling line is the better supported, then the longer. Merging statements (which
  changes colours) still needs two "yes". Two sides of a dispute and an old/new figure are never folded. A
  sentence may carry facts of different colours in up to 3 parts (owner: "each sentence can have multiple
  colours"). Splitting stays: on 13970 one definition sat inside three different compound lines, which no fold
  can join. `CONSOLIDATE_VERSION` 11.
- **Paragraphs of a readable length, by code (owner, Oct 9 2026, story 13792: seven one-sentence paragraphs,
  one of 14).** `narrative.shape_paragraphs`, after the writer and the coherence rewrite: within a section,
  neighbouring paragraphs of up to 2 sentences are joined (up to 4); a paragraph over 6 sentences is cut into
  paragraphs of 2-5 where the speaker or subject changes, never before a sentence leaning on the one before;
  the lead is left as written; sentences are never changed.
- **A fact is not written twice in two colours (owner, Oct 11 2026: "J&K is an integral part of India, reiterating that
  J&K is an integral part of India, Bedi said", green half and purple half).** Cause: the short plain line and an outlet's
  line with a speaker were "covered" (`relate`), the short one was better supported, so `fold_covered` set `adds_to` and the
  writer was told to write both "in two parts"; the long line added only the speaker and "reiterated". Now (1)
  `compose.adds_detail`: `adds_to` only when the long line adds a number, a name (the speaker's own name and a name only
  capitalised by its place in the sentence aside) or a content word (`MIN_EXTRA_WORDS` = 1; speaker and speech verbs,
  `SPEECH_ONLY`, are not content); otherwise it folds like any covered line (the long line keeps its speaker and its own
  colour, the short line's outlets are added as sources). (2) `sentences.collapse_same_parts` (in `polish`, counted as
  `flow.merged`): a sentence whose parts `relate` calls same / covers is collapsed to one (the covering part stays, lead-in
  "adding that / reiterating that" taken off, ids joined = the weakest colour), kept only if every check passes. Not
  handled: two parts that say the same in other words that code calls "different" ("appropriate" / "fitting"); the
  dupes step has to propose those. Old articles are closed and keep their text. Tests ran on a stubbed harness
  (no sqlalchemy / snowball / pytest in the sandbox), not on real stories.
- **Blue = "partly backed by others" (owner, Oct 11 2026; first called "one outlet in full, others in part").** A line that got folded (`fold_covered`) keeps its own
  verdict, but when its sentence then shows superscripts of 2+ INDEPENDENT outlets (its own group plus the groups of the
  lines folded into it, `item.groups` + `item.folded_groups`, owner groups and wire copies merged as everywhere) "one
  outlet only" would contradict what the reader sees. `narrative.shade` returns `partial`: RANK 3, between unverified
  (2) and single (4) (ranks renumbered: disputed 5, false 6; `recap.CLASS_RANK` the same), writer label "PARTLY BACKED
  BY OTHERS", grammar shape plain like single. Only for verdict unverified/pending with n_sources <= 1; it
  never makes anything green. Site: `--par` #2b62ad (text), `--bar-p` #4a86d6, `.s.partial`, legend and bar (key `p`
  after teal, in `feed.bar_counts` and the site's own `barCounts`), English and Hindi labels, `sw.js` cache np-main-31.
  Articles already published keep their old class (closed); `editions.mature` recomputes by `shade`, so a stored
  page whose items lack `groups` / `folded_groups` stays purple.
- **Synonyms live in `config/synonyms.yaml` (owner, Oct 11 2026: "where they can keep on adding").** `relate.SYNONYM` is
  built from it (`load_synonym_groups`, `build_synonyms`; a word stays in the first group it appears in; a missing or
  broken file falls back to `DEFAULT_SYNONYM_GROUPS`). One line per group; the header of the file states the rule: only
  words that mean the same in a news sentence, never different severity (injured / killed, arrested / questioned). Added
  on Oct 11: appropriate fitting apt suitable proper; terror terrorist terrorists terrorism; probe investigation inquiry;
  protest demonstration agitation; and a few more. A lead sentence's pair that differs by a name only (a plain line
  "... against India" and a line with a speaker, "... , Bedi stated") is NOT merged by code: the speaker's name stops
  `covers`, which also protects a statement's attribution from being folded away; the topic step (`dupes.py`) proposes
  such pairs and the model is asked twice.
  **Synonyms learned from the outlets, done (owner, Oct 11 2026: "like the project learns and grows the titles' list on
  its own, can synonyms grow too")** (`learn_synonyms.py`, `config/synonyms_learned.yaml`,
  `.github/scripts/learn_synonyms.sh`; no model; the twin of `learn.py`). The evidence is what the pipeline already
  decided: two claims under ONE merged statement (`claims.canonical_id`: the model said "same" twice, A/B swapped) that are
  word for word the same except ONE lower-case word in the same place (3+ words around it, same numbers and names, not a
  negation, number, filler, same stem or opposite by prefix: `swap`). Only a pair that code alone did NOT already call "same"
  (`relate.relate`) counts, so a long line code merged with one word different (injured / killed) proves nothing, and the two
  claims must come from different independence groups (`wire.independence_groups`). A pair is learned when it shows in 3+
  statements, 2+ stories and 2+ independent groups of outlets and nothing is against it: the two words never stand in one
  statement, never differ between two statements the pipeline judged contradictory (`canonical.conflicts`), are not on a
  `never:` line of `synonyms.yaml` (seeded with the opposites and severity pairs: injured / killed, arrested / questioned,
  raised / cut, rose / fell ...) and are not struck out in `rejected:` of the learned file. Neither word may already be in a
  group (a word stays in the first group it appears in; a learned group never grows by itself); at most 5 pairs a run. The
  entry is one line `{words, learned, statements, stories, example: [2 sentences]}`, only APPENDED. `relate.load_learned_groups`
  reads it AFTER the hand-written groups (they win), drops a learned group that joins two words of a `never:` line, and a
  missing or broken file adds nothing. The job step "Learn synonyms from the outlets" in `hourly.yml` (after the titles step,
  `continue-on-error`) runs `learn_synonyms.sh`: pull, `python -m nishpaksh.learn_synonyms`, commit ONLY that file, push; used
  from the next run on (`relate.SYNONYM` is built at import). A WRONG ENTRY: delete its line, add its two words as one line to
  `rejected:` (and to `never:` in `synonyms.yaml` to keep them apart everywhere). Run by hand: `python -m nishpaksh.learn_synonyms
  --dry-run`. Window: the last 3 days of articles (like titles), so a rare pair may never gather enough evidence in one window;
  keeping a running tally across runs is not built. NOT RUN ON REAL DATA: 5 new tests ran as plain Python (stemmer stubbed, no
  pytest / sqlalchemy in the sandbox), and thresholds were checked by mutation; the database read in `learn_synonyms.run` and
  the git step have not run.
- **What already happened is not written as scheduled (owner, Oct 9 2026, story 13792: "The 57th GST Council
  meeting is scheduled to take place ... on Thursday, October 8", written after it).** `compose.drop_past_schedules`
  before writing: a line saying something "is scheduled / set / expected to", "will be held / take place ...",
  dated before today (IST), is left out; dated today, only when another line reports a decisive act with the same
  names. A line with no date is kept (code never guesses).
- **"Separate" only when the outlets say it (owner, Oct 9 2026, story 16000: "In a separate case, ..." printed for
  the story's own case, a line reading had filed as a related event).** Like an act verb, the word is the outlets':
  `narrative._no_separate` (in `_finish`) removes "In a separate case,", "Separately,", "in an unrelated incident"
  unless the statements behind the sentence use "separate"/"unrelated"; the "Related events" heading tells the reader
  it is another event, and the writer is no longer told to mark related events as separate.
- **"Explained" keeps what reading labels explanation (owner, Oct 9 2026):** a decision filed there is not moved
  ("better more than less").
- **A sentence is a sentence (Oct 9 2026, story 13792: lead "An unnamed source said on Thursday."; "... on
  Thursday," then "And tax officers ...").** Pieces the writer returns apart are joined by code
  (`narrative._join_fragments`: a piece ending in a comma joins the next; a lower-case piece joins an unfinished
  one; different statements = coloured parts); a lower-case slip after a full stop is capitalised; anything that
  still does not start and end like a sentence is refused ("not a full sentence") and the fill pass rewrites it.
  A speaker's surname twice in one sentence is a repeated name ("Sitharaman said ..., and Sitharaman said").
- **A sentence in coloured parts (owner, Oct 7 2026).** A sentence joining statements of different
  statuses is written in at most two "parts" (three since Oct 8 2026, see "One fact per statement"; main fact first, split at a comma or "and"), each citing
  only its own statements; the site colours each part, the source numbers follow the sentence. Code
  checks every part on its own (`narrative._part_ok`: its numbers, names and most of its words from its
  own statements; the parts together are the sentence and all its ids); any failure removes the parts
  and the sentence has one colour, the weakest, as before. A covered short line that is BETTER supported
  than the detailed line is not folded away: the detailed line gets `adds_to` and the writer is told to
  write the two as one sentence in two parts. Parts mature like sentences (`editions.mature`); the
  Hindi page has no parts (one colour per sentence); the said-chain rewrite skips sentences in parts.
- **News first (Oct 6 2026):** the article opens with what makes it news today, never the setting;
  since Oct 8 code chooses it (see "The news, the lead and the headline").
- **Three relations:** same / contradiction (both cannot be true as facts: amber) / RESPONSE (a party
  answers a claim or finding: both true as reports, written together, never amber). "No denial" in
  the green rule means nobody denies the EVENT happened, not that a party objects to it.
- **Essay integrity:** a sentence leaning on the previous one ("He added", "denied this") falls with
  it; a statement and its contradiction/response are both in the essay or both under it; statements
  joined in one sentence must share a subject; "Also reported" skips what the essay already says;
  one repair call rewrites failed sentences before anything is dropped. Headlines must keep who did
  what (`compose._actor_problem`). Reports naming different actors for one fact block green; code checks every such model call: names
  appearing together in one sentence of a statement or report, not joined as aliases ("alias", "urf",
  brackets), are two people and never "named in reports as" each other (`consolidate.named_together`,
  Oct 7 2026: two arrested men written as one).
- **Everything in the article, in sections with headings (owner, Oct 5 and Oct 7 2026):** code puts every
  statement in exactly one section (`narrative.assign_sections`), and code puts them in this order
  (`narrative._in_order`, owner Oct 7 2026: a reader with no prior knowledge gets the context first):
  news (1-2 sentence lead, no heading), Background, What happened, What they say, By the numbers, Explained,
  What next, Related events (owner, Oct 15 2026; numbered 01-07 on the site; it was Background, Explained, What
  happened, By the numbers, What they say, Related events, What next). The site (`sectionGroups`, `pageOrder`) and the
  read-aloud (`audio._page_order`) show older articles in the new order too, by display only (stored paragraphs and
  their indices unchanged, so audio timing still lights the right sentence). NO
  disputed section (owner, Oct 7 2026): a disagreement is written where its subject is, with both
  versions and whose; contradicting statements and claim/response pairs share a section; purple
  one-outlet lines stay with their subject (the colour marks them). One sectioned draft,
  then a FILL pass: each group of sections (news+happened+numbers / say / background+related+
  explained+next) that left statements out or has failed sentences gets its own small writer call,
  kept only if the article then carries at least as much (Flash-Lite given all 40 statements wrote 10
  sentences; a few at a time it uses them). `essay_ok` needs 85% of ALL statements (owner: the middle
  way; since Oct 9 2026 folded lines are not counted: facts, not statements). `narrative.section_keys` (one per paragraph) drives the headings on the site, English and
  Hindi. Leftovers stay in `narrative.not_in_essay`. **A short article is finished, not thrown away (owner, Oct 7 2026):** each try runs up to two fill rounds; a draft still under 85% is kept in `stories.analysis.writer_draft` (sections + model) and the next try resumes it with fills only (no new draft call, up to three fill rounds); new statements count as missing and are filled in; statements merged since the draft are followed through one report behind each (`writer_draft.anchors`, `compose._remap_draft`), so their sentences are kept; the draft is removed when the article publishes. (`recolour`/`needs_rewrite` unused: articles are
  closed.)
- **Who speaks is code's job (owner, Oct 8 2026, story 13107; `voice.py`).** "Humayun Kabir added that ... Humayun
  Kabir also stated that ... Humayun Kabir further stated that ..." came from four layers each patching one
  sentence. Now: (1) a statement "X stated/said that Y" is given to the writer as Y, said by X (`voice.split`,
  neutral verbs only; "accused X of", "denied" keep their verb); (2) the VERB is the outlets': "said" unless the
  statement itself uses a stronger one; the validator rejects "accused", "denied", "threatened", "claimed"... the
  statements do not use ("verb the statements do not use"); (3) PRONOUNS only with evidence (owner: a wrong one
  harms a real person): two outlets' statements use he/she for the person, no other person named in them (bodies
  like "police" are fine, "a sub-inspector", "his son" are not), none use the other; otherwise the surname or the
  role ("the MLA", only when one person has it). The validator rejects an unsupported pronoun ("pronoun without
  evidence") unless the statements behind the sentence use that very pronoun; code never writes one without
  evidence; (4) a speaker named in one paragraph carries into the next paragraph of the same section; (5) a
  paragraph's coherence is measured by code (`voice.problems`: one speaker named in 3+ sentences, "also stated /
  further stated", the same opening twice, sentences over 45 words, 7+ sentences); it decides the coherence
  rewrite AND whether the rewrite is kept (it must have fewer problems: a rewrite that split one block into four
  paragraphs, each opening with the full name, had been kept); (6) the code floor (`style.vary_attribution`,
  `style.Refs`): a run of one speaker becomes "..., he said." / "..., the MLA said." / "..., Kabir said." (rotated;
  "he" only with evidence), and "also stated"/"added" opening a paragraph becomes "said". Sentence-opening words
  ("While", "Meanwhile", days, months) are never part of a name (`style.LEAD`: "While Humayun Kabir" had stopped
  the surname from being used).
- **One speaker's argument told together; the attribution is the statements' speaker (owner, Oct 9 2026, story
  16197).** "The Centre alleged ... overreached the court's judgment" and "The Central government alleged ... less
  than six months" sat in two paragraphs with other speakers between and read as two different claims; the Centre's
  line was printed as "..., the advocate alleged" and the Supreme Court's as "..., she said" (style read "The ..."
  and "He" as whoever spoke before; on the 30 latest articles also Scindia's figures as "Modi said", Rahul Gandhi's
  lines as "Kharge said"). Now: (1) `voice.speaker_key`: one key per speaker (the Centre = the Central government =
  the Solicitor / Attorney General; the Supreme Court = the bench = the CJI; a person by surname); (2) the writer gets
  "What they say" grouped by speaker (`narrative._by_speaker`, an answer right after what it answers) and is told to
  write each speaker's lines in one paragraph; (3) code regroups a "What they say" section whose speakers are
  scattered (`narrative.group_speakers`, sentences unchanged, before `shape_paragraphs`); (4) the validator refuses
  "wrong speaker" (`voice.wrong_speaker`: the name a sentence gives must be the statements' speaker, an alias, or
  a role of that person; never a role for a body; he/she only for that speaker with evidence) and "speaker named
  twice" (`voice.double_attribution`); (5) `style.vary_attribution` refers to each sentence's own statements'
  speaker, and a body is never "he" / "she".
- **A body's run of lines (owner, Oct 9 2026, story 16708: "The US Department of State said that ..." three times
  in a row).** People already got "..., he said." / "..., Kabir said."; bodies got nothing. Now (`style.vary_attribution`
  body branch, `voice.is_body`, `voice.body_refs`): in a paragraph, the second and later lines of the same BODY (by
  its statements' speaker key) end "..., the department said." / "..., it said." (rotated; a plural body: "...,
  they said." / "..., the officials said."), and "The US Department of State identified ..." becomes "The department
  identified ..."; never when the line opens with the body's own pronoun ("its primary activity"). A foreign
  government is one speaker however named (`voice._country_gov`: "US Department of State" = "US officials" = "the
  United States government"). People are unchanged: he/she only with evidence, else the surname or role (singular
  "they" for a named person was not adopted: it reads as plural next to bodies). A person missing from the name
  list is referred to by surname, never "the Raghoo Puri".
- **Introductions:** every person and body at first mention with the fullest name and role the
  statements give (`narrative._people` lists them for the writer); extraction names people in full.
- **Attribution like a newspaper:** name a speaker once, then the surname, the role, or "he"/"she" only
  with evidence (see "Who speaks"); a dispute states both versions and whose they are, never "other reports
  differ".
- **Red verdicts on hold** (`SETTINGS.model_verdicts = False`): no second model family on the free
  tier now Gemma fails most calls. Code verdicts still run. Tests keep the machinery on (conftest).
- **The news, the lead and the headline: one structure (owner, Oct 8 2026; `news.py`).** The news is
  chosen ONCE by code (`news.pick_news`, no call): the story's own statements (not context, not FALSE),
  ranked: not old (an older year, "previously", "had announced" = the past) > a decisive act (deaths
  first; verbs only: arrested, ordered, signed... over held, met, heard; "not" = -1) > HOW MANY OUTLETS tell
  it (a fact's outlets: its own, folded lines', and statements telling the same act in other words) > dated
  on the story's newest day or the day before > central (shares the story's subject) > names and numbers.
  Outlets before the date since Oct 9 2026 (owner; story 13792: a vague one-outlet line dated today beat the
  arrest-power decision three outlets carried). The lead can carry TWO facts (`news.lead_news`, payload
  `lead`): the best-reported one, and when that is not today's, the best decisive fact dated today (not the
  same act in other words), told in the second sentence; the lead must cite the first. "The same act in other
  words" (`news._same_act`): same decisive verb AND a shared number, or a shared name and most of the smaller
  line's words; a shared name alone made every "the GST Council approved ..." line tie (13792 replay). A line one
  outlet tells never leads over a fact 2+ outlets tell, whatever its verb (story 13058, Oct 9 2026: "Nana Patekar ...
  won millions of hearts", one outlet, led the India Mobile Congress story); among 2+ the act still ranks before the
  count (outlets first lost deaths and a bounty on the 30 latest articles). "inaugurated", "unveiled", "issued" are acts. Checked on the 30 latest
  articles. The writer gets it as SECTION news; the lead must cite it (`narrative.lead_ok`, else the news
  fill rewrites the lead). The headline is written after the article (`news.write_headline`): one call
  gives three candidates; code rejects (>12 words, any "reportedly"/"reports say", bare name, loaded word,
  cause word, number or name not in the statements, who-did-what, a DISPUTED figure stated as fact:
  disputes may be the news, owner Oct 8, but the headline says whose version or leaves the figure out)
  and scores the rest on the six principles (the outcome not the process, one concrete detail, a known
  name or role, 7-12 words, no jargon, about the news); a second call only if all three fail; no
  headline = the article waits as a kept draft. House style by code: PM, CJI, CM. Removed: the draft
  headline before writing, the ESTABLISHED/REPORTED labels and "must hedge" rule, the "reportedly"
  fallback, and the per-story importance call (front-page rank = `priority` score + coverage; filler is
  filtered by `priority`). Headline calls per try: 2-7 before, 1-2 now.
  **Headlines made to be read (owner, Oct 12 2026: \"weak, old-sounding, just a name and what happened\").** The prompt now
  asks for three headlines that lead differently (the outcome / the one specific or surprising detail / the stakes),
  about the NEWEST development: `write_headline(..., latest=)` gets the lead's second fact (`lead_news`, the fact of
  the day) and the scorer prefers a headline that shares its words (`headline_score(h, news, latest)`). New code
  rejections (`headline_problem`, same order as before, all by code): a question, \"!\", \"what we know\", \"explained\",
  \"shocking\" (`WEAK`); anything pointing to the past (`PAST`: earlier, previously, \"had ...\"); and a headline that
  OPENS with the name of a person readers do not know (`_opening_name_problem`: persons are proved by a title or
  speech verb (`style.people`) or introduced as a stranger (\"Name, 21,\" / \"Name, a student\" / \"Name was found
  ...\"); a role written first (\"Actor Rajpal Yadav\") or the event first is fine). Names every Indian knows may open
  one: `config/known_names.yaml` (owner can extend; a surname alone counts only when it belongs to one known name).
  Still 12 words at most (card width). Published headlines never change, so this shows from the next new article.
  **A headline never repeats an earlier one (owner, Oct 13 2026: follow-ups carried their parent's headline, later stories
  an older story's).** `compose.recent_headlines` (published, last 7 days, not this story) and the story's parents' headlines
  go to `write_headline(taken=, parents=)`. The prompt shows the parents and the 6 closest ones (`TAKEN_NOTE`) and asks for what
  THIS article adds. By code (`news.repeats`): a correct headline that shares 4+ content words and half of the shorter
  headline's (or 3 words and three quarters) with a taken one is a repeat, whatever the verb (stemmed words, numbers count).
  A repeat loses to any fresh candidate; if both tries give only repeats, the least repeated is used (an article is never
  held back for this). Tune with `REPEAT_SHARED`, `REPEAT_RATIO`, `REPEAT_CLOSE`.
- **Threads:** a later development links to its earlier story (parent → daughter, many-to-many).
  Daughter opens with the new development + ≤2 background sentences + "Earlier in this story"; the
  parent gains no link (it is closed). Archived parents are found through the branch index.
  Front page: one entry per thread (its latest development), NEWEST FIRST by publication time (owner,
  Oct 6 2026; was ranked by importance and read as random); top 20, then "More stories". Filler is never published. A thread timeline page is a possible later step.
- **Grouping:** one embedding model only (`gemini-embedding-001`, chosen on 216 labelled real pairs);
  join only on high similarity to closest members and the story's fixed core, a model checks the
  middle band, stories holding separate events are split. When unsure, keep apart. The middle-band
  question (Oct 8 2026, story 13968: a Ludhiana sarpanch killing of Oct 4-5 merged into a Tarn Taran
  sarpanch killing of Oct 6 on one question about two headlines) compares the article with the story's
  CORE article (IST date, headline, opening words; worked examples incl. the sarpanch trap), asked
  twice A/B swapped, two "same" join, unsure = different; a borderline article published 12 h+ before
  the story's first report (`story_before_hours`) is never asked in (an earlier event).
- **Reading site nishpaksh_version_1.0 (owner, Oct 8 2026; `site/`, the main address; `/v1/` redirects there).** Designed on a canvas
  (trial versions 0.1-0.6) and approved: one card at a time (swipe up/down, snap, loops newest <-> oldest),
  the card shows the headline then the article itself fading out, a colour bar (green / teal / purple / amber / red /
  brown shares of the article's coloured pieces) with the time beside it. **Version 1.1 (owner, Oct 8 2026, after
  reviews said the multicolour sweep and the rounded sans looked like Instagram):** header and article headline
  box = one indigo gradient, light to deep (#46549a -> #161a38); headlines Newsreader (Hindi: Noto Serif
  Devanagari); greeting upright Newsreader / Tiro Devanagari by IST time; wordmark Alfa Slab One / Rozha One
  (Hindi); EN/हिं switch. Tapping a card grows it into the
  article (clip-path from the card, headline glides into the gradient box); back gesture closes it. The
  article keeps everything the old page had (sections, colour key, source numbers, sources, threads, notes,
  framing, perspectives) and "Who reported what" (folded; outlets link to their articles). Mobile first;
  laptops get the same deck centred (a laptop design is for later). The old list-style site and the old
  Streamlit app were removed (owner, Oct 8 2026); links of the form `?lang=hi#/story/<id>` still work. Data: `nishpaksh/feed.py` writes `en.json`, `hi.json` (cards) and `story/<id>.json`
  (slim pages) to the `feed` branch after every desk and pipeline run (`.github/scripts/publish_feed.sh`,
  one commit force-pushed, `continue-on-error`); the site reads them from raw.githubusercontent.com and falls
  back to Supabase, then the archive branch. Service worker keeps the page and last news offline.
- **Site sections (owner, Oct 9 2026; `categories.py`).** Five primary sections, five secondary under each, chosen
  with the owner from ~490 rated stories (politics ~30%, crime/courts ~25%, world ~11%, accidents/weather ~8%,
  business ~7%, health/education ~7%, defence ~5%, films ~3%, sport ~1%: sport is too thin for its own section):
  Politics (Elections, Parties, Government, Parliament, Protests) · Justice (Crime, Police, Courts, Corruption,
  Terror) · Business (Economy, Companies, Markets, Your money, Domains > HR, Finance, Marketing, Analytics,
  Operations; Oct 9 2026, see "Domains and Sport") · World (Diplomacy, Indians abroad, Conflicts,
  Defence, Abroad) · Life (Health, Education, Accidents, Environment, Sport & films). Owner: short, catchy names;
  at most five of each (the site's bottom bar). An article gets up to 2 primary and 2 secondary
  (`payload.category`, keys, first = main; same in Hindi; labels in `categories.labels`, in en.json/hi.json
  `sections`, cards `cat`). One page call at publication (headline, lead, top statements; asked once: a section
  colours and merges nothing); code keeps only listed keys, a secondary brings its primary, unsure = primary
  alone; no answer never holds an article back. Live articles from before sections get theirs on desk runs
  (`fill_live`, 5 per run, only the section is added). **Site display (owner, Oct 9 2026, canvas "Sections A"):** a
  bottom bar in the header's indigo, joined to the bottom edge, rounded on top: All + the five primaries. Tapping a
  primary slides it to the LEFT end where All was, it becomes the back button (‹), the others give way to its five
  secondaries; a secondary filters and the bar stays (tap again = the whole primary); back = all. Labels on one line,
  measured, one font size for every row, equal space between labels; sections with no story yet are lighter and open
  an empty card ("Nothing in X yet" + Show all news). The cards fade and restart at the section's newest. The bar
  slides down off the page while an article is open. Filtering is client-side over every card in the feed.
  **Back to the latest (owner, Oct 9 2026, canvas "Latest 3b"):** two cards or more from the latest (one, in a section
  of two or three; either way round the loop), the CHOSEN button (All, ‹ section, or a sub-section) grows a little and
  shows an arrow at its right end, pointing to where the latest is (down when swiped up past it). Its left half does
  what it always does (back; a sub-section turns off); its right half goes to the latest (`#sb-latest`, a touch area
  over it); All: the whole button. Tapping the wordmark also goes to the latest. Bar classes are prefixed `sb-`: a
  class named "back" once picked up the article back button's shadow. Share: a button at the right of the article's
  sources and time line (the phone's share sheet, else the link is copied).
  **Depth and motion (owner, Oct 9 2026, canvas "Swipe depth 1 — Tilt"):** while swiping, the card leaving tips back
  (rotateX up to 10 deg, back 120 px, scale 0.94, opacity 0.65) and the next rises from slightly behind
  (`paintDepth`, on the slots, only the 3 or 4 near the view; at rest nothing is moved; off for reduced motion). Back to
  the latest RUNS through the cards in between (at most five, from five out when further; 260 ms + 90 ms a card,
  the short way round the loop), so it is seen to go there (`toLatest`). **The phone's back in a section** steps out
  one level (tertiary → secondary → primary → all) instead of leaving the site: every level gets its own history
  entry WHEN TAPPED INTO (`{np: "sec", level, sec, ter}`; deeper = push, sideways = replace, shallower through the bar =
  `history.go(-n)`), and back restores the section of the entry it lands on. Entries added while going back were
  skipped by Chrome on Android (no tap = no entry) and the site closed. An open article is closed first.
- **Pictures: collected first, shown later (owner, Oct 9 2026).** Principles agreed: (1) only the outlet's own
  SHARE picture (og:image / twitter:image, else the feed's media:content / thumbnail / image enclosure), LINKED from
  the outlet and credited to it, never copied to us; (2) chosen by a SIMPLE code rule, no image analysis (owner, Oct 9 2026: "we
  don't need complex analysis, just the most relevant one"): the picture of the outlet whose report the lead comes
  from, else the next outlet of the story; an outlet's default logo picture (the same link across its unrelated
  stories, e.g. TASS) is never used. Licence-free Wikimedia pictures were offered and not chosen (generic, often none); (3) a picture that does not load leaves the
  card as it is. Stored in `articles.image` (migration `20261009000100`; "" = looked, none; NULL = not looked):
  `ingest.page_image` / `entry_image` at reading, `discover` for search finds, `ingest.fill_images` looks once at up
  to 60 articles of the last 36 h in a story that have none yet (run stats `images`: with / without / filled).
  **Shown (owner, Oct 9 2026, canvas "Pictures A" and "Article · Calm + tiles + quotes + rail"):** `feed.pictures`
  picks one per live article at every export (the lead's reports first, then the rest; a link on 3+ stories =
  logo) and puts it on the cards (`img`: src, by, href). Home card: the picture across the top, sharp, then
  blurred and washed to white where the headline begins, credit chip "Photo: <outlet>"; a story without one, or
  whose picture fails to load, keeps today's card. Article: the picture at the top of the indigo headline box,
  dissolving into it, credit linked to the outlet's article; the top stays (back · wordmark · language) with the
  wordmark where and as big as on the home page in the home page's indigo gradient; under it a rail of the
  article's sections (the one being read filled, a tap goes there) and a line in the same gradient that fills as
  you read; the lead alone in a larger serif; each section its own card under a numbered heading; By the numbers
  as tiles (the sentence's first figure big, the sentence under it, colours and source numbers kept); What they
  say one card per paragraph with its speaker (`feed._speakers`: the name the reports give most often,
  `narrative.who`, English page only). Display only: the closed article's text is unchanged. **Opening and closing animate by transform and
  opacity only** (Oct 9 2026, jitter on two Android phones): the headline box keeps its open layout, the headline and
  the picture are moved over the card's (`placeOverCard`: --tx/--ty, --pt scale covering the card's picture, --hw = the
  card headline's width so the lines break the same); never animate padding, width, height, top or left there (one
  relayout per frame: 33-40 per animation before, 3-9 after). The article's picture is laid out at its whole cover size
  (`fitPic`) and gets its own transform (`--it`) so it is at exactly the card picture's zoom and crop at both ends; it
  had been over-zoomed while closing and snapped back at the end (owner, Oct 10 2026).
- **No internal notes for readers (owner, Oct 8 2026):** the article page no longer shows "Nothing in this
  story is confirmed by independent sources yet" (read as "this story is fake"; the colours already say which
  parts are supported) nor "Which outlets form different perspectives is not yet known" (internal state, not
  something a reader needs). Keep such status out of the reader's page.
- **Address (owner, Oct 8 2026):** the repo lives in the free GitHub organisation `NishpakshNews` as
  `NishpakshNews/NishpakshNews.github.io`; the site is https://nishpakshnews.github.io ("nishpaksh" was taken). The
  page reads its feed/archive from that repo; `pagearchive` uses `GITHUB_REPOSITORY`; both Supabase dispatch
  functions call `public.dispatch_workflow` (migration `20261008000100_repo_moved.sql`) with the Vault token
  `github_dispatch_token`, a fine-grained token for this repo (Actions: read and write).
- **Egress (Oct 8 2026):** Supabase free = 5 GB/month; the first week used 12.5 GB, ~85% of it the pipeline re-reading
  article text, embeddings and minhashes every run. `heavy.py`: those columns are selected as md5 and served from a
  local SQLite cache (kept by actions/cache in hourly.yml, `NISHPAKSH_HEAVY_CACHE`), fetched only when new or changed;
  run stats `heavy_cache` (hit / fetched). Article choice reads text lengths, then the text of the chosen articles only;
  priority reads only stories with a fresh report; the feed re-reads only articles whose payload md5 changed
  (`manifest.json` on the feed branch). Keep new heavy reads behind `heavy.columns`/`heavy.fill`.
  **Oct 10 2026 (still ~1.7 GB/day after the cache; the org went over quota):** the thread check read every live
  page (~70 KB each) for every story it checked: it now reads only the headline and first two lead sentences in
  SQL (`threads._slim`); `editions.mature` reads a page only when its verdicts changed since the last maturing
  (`stories.analysis.mature_sig`, set in SQL with jsonb_set); per-story text reads (origins, perspectives,
  consolidate, extract) go through `heavy`; the desk (writer.yml) uses the same cache; the site tries the feed
  twice with 15 s before reading Supabase (5 s fallbacks read ~100 MB a day). Never select a `published` payload
  whole where a JSON path would do. Budget: 5 GB a month = ~165 MB a day for everything.
- **Domains and Sport: one rigorous route, reserved places (owner, Oct 9 2026).** A cheaper "brief" lane for business
  and sport (single source, no embeddings) was designed and REJECTED by the owner: one standard everywhere, same
  depth, same perspectives. Instead: (1) **Business = Economy · Companies · Markets · Your money · Domains**, and
  Domains has a THIRD level, **HR · Finance · Marketing · Analytics · Operations** (`categories.TERTIARY`;
  `payload.category.tertiary`; up to 2 of each level; "business/domains/hr" in the one section call). A domain is a
  LENS over the news, not a pile of news: a story is HR if it changes something for people at work, whatever
  else it is (Oct 2-9: only ~2-5 genuine stories a week per domain among 526 multi-outlet stories). Jobs and Tech
  became HR and Analytics (`categories.normalize` / site `normCat` map old keys; stored payloads unchanged).
  (2) **Reading queue:** of `prep_queue` (16), `prep_beat` (4) go to the best Domains/Sport stories; unused places
  go back (`priority.queue`). A story is a beat story when its desk question says so (`priority.beat_check`, its OWN
  call per 20 headlines, worked examples, unsure = none, asked once, again when coverage grows by 2+; saved in
  `analysis.beat`; scheduling only) or half its articles come from feeds tagged `beat: domains|sport`
  (`priority.is_beat`). Oct 9 2026: asked inside the importance rating it answered "none" for all 36 stories rated
  in its first 3 hours, among them Indian IT firms suspended from the US green card programme, the anti-cancer
  drug margin cap and the Starlink row, so the beat seat stayed empty every run. (3) **Desk seats:**
  at most 3 an hour, 2 for any story (`desk_per_hour`), 1 only for Domains/Sport (`desk_beat_seat`), filled by a
  beat story first; with none ready it stays EMPTY (`desk.seats`; diagnostics `beat_seat`). (4) Specialist feeds
  (Moneycontrol, ET Markets, ESPNcricinfo ...) are ordinary feeds with `beat:`, added once embedding room is
  measured; section feeds, not everything-feeds. **Site:** a secondary with sections of its own opens them the way
  a primary does: Domains slides to the left as the back button (‹ Domains) and its five take the other places;
  a domain filters, tapped again = all of Domains; ‹ Domains = back to Business (`sub`, `ter` in index.html).
  Trade-press exclusives (one outlet) are not published: the same rule a niche political story faces.
  **Reversed in part by the express lane, below (owner, Oct 12 2026).**
- **Express lane: topic lanes written from ONE independent outlet (owner, Oct 12 2026; `express.py`, `config/express.yaml`).**
  Why: only political stories were published for hours. All 61 feeds are national / world section feeds (no business, sport,
  health or life feed; `beat:` was defined but unused); the 3-outlet rule sat at every stage (candidate, rating, reading,
  qualifying) so a company announcement with one or two outlets was never read; and the importance rubric rates
  Parliament / courts / security high and product launches as filler. This PARTLY REVERSES the Oct 9 decision above
  ("one standard everywhere"): that rejected a cheap lane with no embeddings and no checks; this one keeps admission strict
  and the colours honest. Decisions (all approved by the owner):
  - **Positive list of lanes, not "all non-political"** (non-political would let in crime, accidents, deaths and
    allegations, where one source is dangerous). Round one: **Companies, Sport, Entertainment, Tech launches.** NOT Economy
    or Markets (government figures and interference; the owner named GDP disputes), NOT Health or general Life (one wrong
    medical claim does harm) until the first batch has been read. Each lane has its own dial in `config/express.yaml`.
  - **Admission test, strict.** One independent outlet (wire copies and same-owner outlets are ONE group, so many outlets may
    carry it) with a fully readable page (headline-only pages are never used: Option B stands); a small model names the lane
    from the HEADLINE, asked twice in swapped order, unsure = not express; code exclusions (`express.excluded`, run before any
    model): crime / arrests / deaths / accidents / courts / accusations (`harm`), a government, ministry or regulator acting
    on or speaking about it (`government`: the same interference problem as markets), share prices and tips (`market`,
    Companies and Tech), speculation (`speculation`: reportedly, leaked, in talks, may / could, predictions), film gossip and
    box-office numbers (`gossip`, Entertainment only: producers inflate them), service pieces / live blogs / listicles /
    opinion / sponsored (`service`, listicle patterns, `exclude_url`). Lists written in lower case match whole words in any
    case; ALL-CAPS entries (ED, RBI, FIR) match exactly as written. Which lanes a list applies to is `apply:` in the yaml.
  - **Honest colours, no new colour rule.** An express article has one independent outlet, so it reads purple ("one outlet
    only") and can never be green (green: 3 outlets, 2 origins, 6 h). The owner asked whether to allow green to keep the code
    simple: it needs no code, green simply cannot happen. A company announcement reads "X said it will ..." (named speaker).
  - **A named origin is required** (the company, the league, an official; not "sources said"). With one outlet a dispute
    cannot be seen, so (a) the main fact must trace to a named origin; (b) during the one-hour wait for a second outlet, if one
    turns up the existing dispute and denial checks run on it (today they run only at 3+ outlets: lowered for express only).
    No lower bar for later corrections (a lie found after publication stays in a closed article).
  - **Seats:** the beat seat (Domains / Sport, `desk_beat_seat`) goes from 1 to 2 an hour and express stories share it; the
    general seats stay at 2; a seat stays EMPTY if nothing passes the test (quality is kept in admission, not by starving).
  - **Intake:** a separate express intake: section feeds (business, sport, entertainment, tech) of outlets already in the app,
    tagged `lane:` in `feeds.yaml` (matched by URL like `beat:`, no schema change). Verify each with
    `python -m nishpaksh.tools.check_feeds` on GitHub's runner (the sandbox has no network); paywalled papers stay out.
  - **Embedding budget:** the tightest quota (3,000 texts a day over 3 keys, all used). Express gets a DAILY slice
    (`embed_daily_cap` = 400, about 13%), spread by the existing pacing; every article must be embedded to find out it is
    alone, so the saving comes only from the headline filter: one cheap model question per 20 headlines, and only a
    headline that passes a lane is embedded. Re-read the real use after a few runs (the ledger) and adjust the cap.
  - **Settling:** wait about an hour for a second outlet, then write. A fixed number of express READS per run
    (`reads_per_run`) so the Flash-Lite quota is not drained.
  **Build status (4 parts, each fits one session):**
  1. DONE (Oct 12 2026): `config/express.yaml` (lanes, exclusions, dials); `express.py` (config, `lane_feeds`,
     `excluded`); the ledger (below); tests `tests/test_express.py`, `tests/test_ledger.py`.
  2. DONE (Oct 12 2026, Part 2; NOT RUN ON REAL DATA, the sandbox has no network, sqlalchemy or pytest): the express intake,
     the headline question and the embedding slice.
     - **Feeds** (`config/feeds.yaml`, tagged `lane:`; matched by URL like `beat:`, no schema change): 24 ENGLISH section feeds,
       6 outlets (Hindustan Times, Times of India, Indian Express, News18, Firstpost, The Hindu) x 4 lanes (business ->
       `companies`, sports, entertainment, tech). The URLs are from memory and UNVERIFIED: first thing to do is run
       `python -m nishpaksh.tools.check_feeds` on the runner (workflow `probe`, part feeds; it now prints the lane and URL) and
       delete the ones that fail (a feed failing 24 runs in a row is switched off by itself). Hindi section feeds and
       specialist feeds (ESPNcricinfo, Moneycontrol; paywalled ET / Business Standard / Mint stay out, option B) are NOT
       added: wait for the ledger. Network18 owns News18 + Firstpost (one independence group), so round one has 5 groups.
     - **Intake** (`express.take_intake`, called by `ingest.ingest`): express links have their own caps (`intake_per_feed` 12,
       `intake_per_run` 80; the main feeds keep their 400 and 30) and the code exclusions run on the headline and the feed's
       blurb BEFORE the page is fetched (no download, nothing stored). A lane feed while `enabled: false` (or an unknown lane)
       is not read at all (`express.skip_feed`), so section feeds never reach the strict politics grouping by accident.
       Intake diagnostics are keyed "Outlet [lane]" (`ingest._dk`; several feeds share an outlet name).
     - **The gate** (`express.gate`, called in `stories.group_stories` next to `worldgate.hold`; a failure there only holds the
       express articles, never stops politics grouping): for an UNREAD express-feed article with no vector: page not readable
       (`text_source == summary`) -> no (Option B); code exclusions with its lane's own lists -> excluded; else the headline
       question (`express.lanes_agreed`: `page` tier, batches of `filter_batch` 20, at most `filter_calls_per_run` 6 first-asking
       calls a run, newest first; the second ask only for headlines that got a lane, in REVERSE order; a lane counts only if both
       answers name the same lane, else "none"; a headline the model did not answer, no quota or a failed call stays UNDECIDED and
       is asked next run); the lane's own exclusions run again on the lane the model named. Worked examples for the small model
       are `filter_examples` in `express.yaml`. Only a "yes" is embedded.
     - **The verdict is kept with the article** in `articles.extraction["express"]` = `{v: 1, verdict: yes|no|excluded, lane, why,
       at}` (an unread article's `extraction` was unused; `extract._extract_one` now carries the key over when it writes
       `{model}`; a `VERDICT_VERSION` bump re-judges everything). A headline is therefore judged once.
     - **The slice**: express articles that passed are embedded FIRST in `_embed_missing(first=...)` (a reserved place and a
       cap), within `embed_allowance` = `int(cap * router.pace_fraction(now)) - used today` (the same pacing curve as the other
       quotas), counted in `quota_usage` as model `express:embed` per Pacific day (`express.book_embedded`; the same table
       `carry:*` uses). A passed headline beyond the allowance waits (verdict stays "yes", found again next run). Nothing is
       asked once the day's `embed_daily_cap` is used. Express articles are NOT taken out of the politics budget in advance:
       they take their (capped) share first, politics gets the rest of the run's budget.
     - **Funnel** (`express.STATS`, saved as `runs.stats["express"]`, printed by the ledger): `taken`, `intake_excluded`,
       `intake_over_cap`, `unreadable`, `asked`, `not_lane`, `passed`, `passed_<lane>`, `embedded`, `calls`, `excluded` {list: n},
       `excluded_terms` {"list:word": n} (the ledger prints the top 25 words: loosen the ones that keep out good stories),
       `now` {cap_left, allowance, passed_waiting, undecided}. `EMBED_STATS` also has `held_express`.
     - Tests: `tests/test_express_gate.py` (plain logic, 22 tests, ran in the sandbox with a stand-in runner; mutation-checked)
       and `tests/test_express_db.py` (through the database; NOT RUN: needs sqlalchemy / pytest). `_embed_missing`'s new order
       was run alone against fakes.
     - **Already useful before Part 3:** an express-feed article that passed is embedded and grouped like any other, so a sport
       or company story that three independent outlets carry now reaches the normal strict route (rating, reading, writing) and
       the beat seat; what Part 3 adds is one-outlet stories.
  3. DONE (Oct 13 2026, Part 3; NOT RUN ON REAL DATA; the plain-logic tests ran in the sandbox, `tests/test_express_story_db.py`
     needs sqlalchemy and runs on the runner). Built from the first 9 runs of the ledger (see "What the ledger showed" below).
     - **An express story** (`express.candidates`): unpublished, fresh, a member whose stored verdict is "yes" with ONE lane; any
       member judged excluded or off-lane, or whose headline any exclusion list matches, keeps the whole story out (`story_lane`);
       1 or 2 independent readable outlets (3+ is the normal route; `normal_route_outlets`).
     - **Reading** (`express.focus`, added to `focus` in `run.py`, `extract.select_for_extraction(express=...)` reads from the first
       independent source instead of the third): `reads_per_run` 3 NEW stories a run, newest first, plus every story already
       begun. Its own cap, apart from the 16-place preparation queue. At 2+ outlets `consolidate_story` runs for express stories
       too (it marks conflicts).
     - **Qualifying** (`express.assess`, code only, in `analyse` and the second loop of `run.py` after the normal rule):
       every independent outlet with a readable page has been read (a second outlet is never skipped: `second_outlet_unread`);
       with 2 outlets nothing is disputed (a `conflicts` mark or a "denies" claim: `disputed`); the statements of what happened
       (`kind` event) name their origin: one anonymous ("sources said", "officials", "analysts"), agency (PTI) or other-media
       ("Bloomberg reported", `media_words`) event and it is out; a named event is needed, except sport, where the outlet's own
       voice stands for a match result (`own_voice_lanes`). Then `perspectives.mark_qualified(sid, "express")`. Unsure = no. The
       reason a story fell out is counted in `STATS["story_out"]`, the ones that went in in `story_in` (ledger prints both).
     - **Settling** (`editions.settle_reason`: `qualified_by == "express"` -> `express.settle_decision`): written `wait_for_second_hours`
       (1) after it first qualified (`met_at`), not by the 8-hour cap or the quiet rule; never when stale. If a third outlet turns
       up the story is analysed again and the normal rule takes over.
     - **Desk**: an express story counts as a beat story (`desk._beats`), so it shares the beat seat; `stats["desk"]["express"]` lists
       the express stories published. Colour: one outlet is "single" purple by `narrative.shade` as always; nothing changed there.
     - **Not yet checked on real data (Part 4 starts here):** that `perspectives.analyze_story`, `compose.build_payload`, `verify.base_verdicts`
       and the writer cope with a story of ONE outlet (read for assumptions, not run); `follow_up_ok` and the essay checks; the
       writer's wording for a company's own claim.
     - **What the ledger showed (9 runs, Oct 2026), which the dials follow:** companies and tech starve (the business and tech feeds
       are mostly economy, markets and RBI items, which are excluded by design), sport and entertainment dominate; the intake caps
       (not the embedding slice) were binding, so `intake_per_run` went from 80 to 120; the writer and reading are the bottleneck
       (217 qualifying, queue of 16, 0-2 published an hour), hence the separate express reading cap and the shared beat seat; the
       Indian Express and Firstpost lane feeds look weak or dead; `harm:detained` hit 91 headlines in business and sport feeds and may be
       too strict. Read `ledger/LEDGER.md` for the new "did not qualify, and why" table before changing any dial.
     - Open question for the owner: sport results on the outlet's own voice (`own_voice_lanes: [sport]`); add entertainment or
       leave it, after the first batch is read.
  4. DONE (Oct 13 2026, Part 4; built from 20 runs / 21 hours of the Part 3 ledger; NOT RUN on real data; DB tests run on the runner).
     - **What the ledger showed:** express works: 110 stories qualified (sport named 50, own voice 30, entertainment named 24,
       companies named 6), 17 express articles were WRITTEN, no problems recorded. Failures were only `not_named` (18) and
       `second_outlet_unread` (4); no dispute was ever found. Tech passed 10 headlines and never qualified; companies passed 10.
       Quota is not the limit (light, page and writer tiers were mostly unspent). The seat is: 5-9 beat stories were ready each
       hour against 3 seats, and the beat seat was full whenever stories were ready; reads were capped at 3 new stories a run with
       about 90-110 waiting, but ready stories already outnumber seats 3 to 1, so more reading would only deepen the queue.
     - **Seats:** `desk_beat_seat` 1 -> 2 (`config.py`), shared by Domains, Sport and express stories; Domains and Sport rank first
       in `desk.ready` (rating), express stories after them. The unused `seats_per_hour` dial in express.yaml was removed.
     - **Reading cap left at 3** (`reads_per_run`), for the reason above; raise it only if `ready_beat` falls below the seats.
     - **Company wording:** `express.qualify` keeps the lane in `analysis["express_lane"]`; `compose.build_payload` passes it;
       `narrative.write_narrative` adds `express.WRITER_NOTE` (a party's claim, plan, price, figure is written as that party's word
       with the statement's own verb, never as established fact, no added praise) for express stories outside sport. A sport
       result stays the reporter's own voice. No new check on the finished article: it is purple "one outlet only" anyway.
     - **Ledger:** "did not qualify" now also by lane (`story_out_lane`), to see which lane `not_named` hits.
     - **Replay:** `python -m nishpaksh.express_replay [word ...]` lists the stored headlines each exclusion word kept out and, for
       named words, which would pass without it (`tests/test_express_replay.py`). The ledger names `harm:detained` (176),
       `gossip:box office` (160), `harm:death` (150), `market:inflation` (164): read their headlines before loosening anything.
       The exclusions were left as they are: false positives cost more than missed stories.
     - **Not done, on purpose:** more company and tech feeds. Their starvation is supply (business feeds are mostly economy and
       markets, excluded by design), and a feed cannot be checked from the sandbox (no network). Add outlets already in the app
       with `tools/check_feeds.py` run on the runner. `own_voice_lanes` stays `[sport]`; entertainment qualified only on named origins.
     - **Still unread by me:** the published express pages themselves (the ledger holds numbers, not text): open a few and check the
       wording for company stories; and `stories_awaiting_regroup` (167 in the last run) holds stories whose vectors came from another
       embedding model, which delays express stories as it does the others.
  5. DONE (Oct 13 2026, owner read the first published express stories: "less impactful ... day to day unimportant"; NOT RUN on real data).
     - **The bar (`express.significance_agreed`, `SIG_PROMPT`, `significance_*` in express.yaml):** after the lane, a second small question
       per headline: `india` (India, an Indian person, team or company is the subject, and it is a real achievement, event or row),
       `world` (the sport / industry / event as a whole moves, or a global figure's national sensation), `none` (a foreign player's
       injury or squad unless against India, private life, cast / crew / signing / sequel details, a minor celebrity, a small company,
       a leak or rumour). Asked twice (second time reversed, only for passes), both must give the SAME class, unsure = none. Per-lane
       notes and the owner's ten headlines with his verdicts are in the prompt as examples. Only india / world are embedded and read.
       The verdict is `{verdict: pending}` while the question is unanswered (a failed call is asked again; the lane is not), then `yes`
       with `sig`, or `no` / `not_significant`. A "yes" from before this question (no `sig`) is asked again and never counts for a story.
       A member `not_significant` keeps its whole story out. Counters: `lane_ok`, `sig_calls`, `not_significant`, `not_significant_<lane>`,
       `sig_india`, `sig_world`, `now.sig_waiting`. Switch off: `significance_enabled: false`.
     - **The strict order (`express.order`, `express.tier`, `desk._beat_order`):** express companies, tech, then the Domains desk, then
       Sport (the Sport desk and express sport are ONE place: merged), then express entertainment; inside a place an India story before a
       "world" one, then the queue's own order. Only the beat stories are re-ordered among their own positions (general stories keep
       theirs), and an express story has the beat seats only, never a general seat. Strict means entertainment gets a seat only in an
       hour nothing above it is ready.
     - **Reading in the same spirit (`express._reading_order`):** `reads_per_run` stories, one per lane in turn in that order, India first
       inside a lane, newest first, so quiet lanes (companies, tech) are not crowded out by busy ones. The story's lane and `sig` are saved in
       `analysis.express_lane` / `express_sig` by `express.qualify`. Counters `started_<lane>`.
     - **Tech:** not proven why it never qualified (the by-lane table was new). Suspects: supply (10 of 421 links), the 3-read cap going to
       sport and entertainment (fixed by the lane rotation), and speculation words (leaks, "likely"). Read `story_out_lane` and
       `started_tech` in the next ledger before adding feeds.
     - Tests: `test_express_gate.py` (significance, pending, off switch), `test_express_story.py` (order, reading order, sig), `test_express_story_db.py` (`_beat_order`).
- **The ledger (owner, Oct 12 2026: "embedding is a lot of confusion ... store them in detail, so we can use them to fine tune";
  `ledger.py`, folder `ledger/`, `.github/scripts/ledger.sh`).** One record per hourly run, committed to the repository (so the
  zip carries it) by a step after the desk (`continue-on-error`; reads only, no model, no quota). `ledger/runs-YYYY-MM.jsonl`
  holds the detail (120 days), `ledger/LEDGER.md` the readable summary of the last 8 days (embedding by quota day, last 24
  runs, per-outlet yield, the express funnel, problems), `ledger/README.md` the field meanings. Embedding detail comes from
  `stories.EMBED_STATS` (saved as `runs.stats["embedding"]`): the budget and how it was computed (left today, runs left, pace),
  waiting new / read articles, what was embedded per outlet, world-held, the yield used for the order; plus the quota counter
  today in total and per key, and per outlet [articles in the 72 h window, embedded, in a 3+ outlet story]. FIRST THING TO DO
  when a zip arrives with `ledger/`: read `LEDGER.md` before changing any budget.
- **Outlets outside India (owner, Oct 9 2026; `worldgate.py`, `priority.py`, `config/ownership.yaml`).** Two jobs:
  India's stories seen from outside (independent origins, real cross-border disputes) and world stories of global
  impact. Indian coverage decides relevance: (1) a world outlet's article joins stories Indian outlets cover;
  (2) Indian outlets' world pages are read too; (3) a story no Indian outlet covers is a candidate only with 3+
  independent world outlets AND two "yes" to one global-impact question (asked twice, reverse order; unsure = no;
  `analysis.world`). Ownership groups carry `region: world` (BBC included) and, for state media, `government:`
  and `voice:`. **State media** (the government controls the editorial line, no legal guarantee of independence):
  their group key is `gov:<government>` (`wire.independence_groups`; a paper carrying "(Xinhua)" copy joins it),
  one origin with that government's officials, NEVER counted as an independent outlet (`wire.independent`:
  reading threshold, rating, origins `outlets`, `n_sources`, perspectives) and never a perspective unit. This
  also stopped PIB counting as an outlet. A statement only foreign state media report in their own voice gets the
  speaker "Chinese state media" etc. (`compose._state_voice`). Owner's borderline calls: Al Jazeera, The National,
  CNA = state; Arab News, DD News / AIR = not. Public broadcasters independent by law (BBC, DW, France 24, NPR)
  are ordinary outlets. Paywalled papers are not fed (option B). **Embeddings** (3,000 texts/day; 2,236-2,975
  used Oct 5-8 before this): a world-feed article is embedded only if it names India, shares 2+ names with an
  Indian headline of the last 48 h, or with headlines of 2+ other independent world outlets; the rest wait and
  are checked each run (`worldgate.hold`, code only). When the budget is short, outlets whose articles end in
  3+ outlet stories go first (`stories._yields`; Aaj Tak home 30%, The Hindu 23%, NDTV India 26%); nothing is
  dropped. An outlet in no group (found by search) is Indian unless its domain is another country's.
- **Scheduling:** Supabase `pg_cron` calls GitHub's workflow_dispatch at :05 every hour
  (`public.dispatch_pipeline()`, token in Vault `github_dispatch_token`); the pipeline has no GitHub
  schedule (removed Oct 8 2026). Since Oct 10 2026 the desk runs in the same job right after the pipeline
  (see "The newsroom lives in the job"); `writer.yml` is gone and pg_cron's desk job (`dispatch_desk`) is off.
- **The newsroom lives in the job (owner, Oct 10 2026: "we have no other option, go for it").** Supabase's free
  egress (5 GB/month) was used ~15 GB in 9 days, ~all of it the pipeline reading its own data back, and the org
  went into its grace period (a transfer to a fresh org is refused during it). Now: every newsroom table (feeds,
  articles, stories, claims, canonical, story_pairs, source_clusters, published, translations, story_links,
  quota_usage) lives in a Postgres 17 SERVICE inside the hourly job (hourly.yml), loaded from the saved copy and
  saved again at the end (`.github/scripts/newsroom.sh`): pg_dump, checked (articles/stories never empty, the
  main tables present), AES-256 encrypted with the `NEWSROOM_KEY` secret (public repo, outlets' text), kept in the
  Actions cache (`newsroom-<run>`) AND force-pushed to the `newsroom` branch (40 MB parts, `NEWSROOM_PART_MB`); restore takes the copy
  with the newer stamp and REFUSES to start with none (never an empty newsroom saved over the real one); save
  refuses unless this job loaded a copy. Supabase keeps the READER tables and the run logs (`db.READER_TABLES`:
  profiles, follows, push_subscriptions, notifications, audio_requests, audio_files, recaps, videos, saved,
  notify_state, account_events, runs, diagnostics): `Store` sends each statement to the database its tables live
  in (`READERS_DATABASE_URL` = Supabase, `DATABASE_URL` = the newsroom; one statement may not mix them: tests run
  split, conftest `two_databases`). The live articles are copied to Supabase's `published` after each save
  (`mirror.py`, md5 per row, JSON copied as exact text; writing is free) for the site's fallback and the audio
  job, which still runs on Supabase alone. One job per hour: gate (Supabase `runs`) -> load -> pipeline (45 min
  budget) -> archive -> desk (20 min) -> save -> [only if saved] mirror, feed, notifications, audio check; a
  published article is shown only once the hour is saved, so a lost hour is re-done, never published twice.
  Tools (replay, modelcmp, probe, daily archive) load a read-only copy (`.github/actions/newsroom-load`).
  `newsroom-seed.yml` made the first copy from Supabase (refuses if one exists unless "replace"); Supabase's own
  newsroom tables are frozen since and must never be written again. Every load/save/refusal is logged in
  Supabase `diagnostics` kind 'newsroom' (`newsroomlog.py`). `heavy.py` is unused in the job (reads are free).

- **Reader features (owner, Oct 9 2026; built functional and plain, the owner designs them later; never ask him UI
  questions).** Guiding rule: personalise by TOPIC, never by viewpoint; perspective sorts were refused ("our project is
  exactly against this"). Supabase migration `20261009000200_readers.sql` (applied): profiles, follows, push_subscriptions,
  notifications, audio_requests, audio_files, recaps, videos, saved, notify_state, account_events; RLS = a reader's own
  rows; `request_audio()` RPC; Web Push key in Vault (`vapid_private_key`, read by `public.vapid_private_key()`, pipeline
  role only; public key in `site/features.js` and `notify.py`).
  - **Accounts:** edge function `supabase/functions/account` (verify_jwt off, checks tokens itself): sign up with name, email
    and password, log in with email and password (2.1; login ids and guests dropped); users made with the admin API, email
    confirmed, so no Auth settings changed. No password reset yet (needs custom SMTP).
  - **Follows are for notifications only** (owner): sections at any level, primary or secondary both count ("any");
    states (`places.py`: the section call names states, code keeps one only if the article names it or a city of it; "New
    Delhi" alone is not Delhi); people/bodies (`people.py`, code only, titles stripped); a single story (a follow-up
    published = notified); the daily recap. EVERY match is notified: no cap, no quiet hours (owner). `notify.py` runs at
    the end of every desk run (queue only), one row per reader+kind+ref, which is also the site's inbox; the hourly job SENDS
    the pushes in its own step after the feed is published, and the site asks for en.json/hi.json with the minute in the
    address (`?m=`) to step past GitHub's 5-minute cache (owner, Oct 10 2026: the home page showed an article 5 minutes
    after its notification). Coming back to the page after 2 minutes away reloads the cards.
  - **Daily brief** (owner, Oct 10 2026, option B; `recap.py`, called by `notify.make_recap` on the desk run from 23:00
    IST): the day's stories section by section (Politics, Justice, Business, World, Life, then "Also today"), ONE short
    sentence per story (its main section only; a thread told twice in the day once, by its newest), most outlets first.
    One page-tier call per section rewrites the stories' LEADS as brief sentences; code checks each against its lead
    (`recap.problem`: numbers incl. number words, names or their initials, "not", the speaker kept, "allegedly" kept, no
    hedge or cause word, no act verb the lead lacks, <= 40 words) and a refused or missing one is the lead's own first
    sentence. NO new colouring (owner: "just use the colour of the sentences used"): a brief sentence takes the weakest
    colour of the lead sentences it uses. Hindi: the brief's sentences through the translation cache
    (`compose.translate_strings`), else the Hindi lead's first sentence. No audio (owner, Oct 10 2026). Payload
    `{kind: "brief", sections: [{key, label, sents: [{t, c, id, p?}]}], stories}`; the site's Daily recap card shows it
    (a tap on a sentence opens its article; older recaps as a list).
    **Pointers (owner, Oct 12 2026):** the card shows each story as its own BULLET (`<ul class="rbrief"><li class="rs">`), not one
    paragraph, so the day's news reads as separate items. Display only: the payload's sentences are unchanged. Since the same day
    each entry of `stories` also carries `n` (independent outlets), `lead` (the article's opening sentences, text + colour; the weakest
    colour of a sentence's parts) and `sx` (1 for a suicide story): what the recap's talk guide reads (below). Older recaps lack them.
  - **Audio on request** (`audio.py`, workflow `audio.yml`, started by the desk when something waits; GitHub schedule every
    3 h as backup): language chosen by the reader; 1 new request per reader per IST day, audio already made is free; every
    "tts" model on every key (10/day each); headline + article as written + section headings; one voice; the site lights
    each sentence in its own colour while it is read (timing file per audio; owner: highlighting only). Files on the
    `audio` branch (force-pushed, live articles and 7 days of recaps), published under /audio/ by audio.yml and site.yml.
  - **Videos** (`videos.py` + `videoquery.py`, desk; REBUILT Oct 12 2026, owner: the names-based search "did not work at
    all"; the old logic and its tiers were scrapped). Once per new article: (1) SEARCH VAGUE: the kind of event, no names or
    figures ("Delhi Police releases detained CJP leader Abhijit after conditional bond" -> "release of detained leader";
    "...opposition march to Supreme Court..." -> "opposition march"). One `page`-tier model call writes the English and the
    Hindi phrase (`videoquery.phrases`, prompt with the owner's examples), every answer checked by code (`clean_phrase`: 1-5
    words, no figure, right script, no name of the headline, shares a word start with it); what the model did not give
    usably, `code_phrase` writes (the headline's plain content words, capitalised words dropped). Two searches (en, hi), 50
    results each, from 30 days before the story's first report; fewer than `MIN_SHOW` (3) videos kept -> the same two
    searches with no date limit. (2) LANGUAGE ONLY WHEN SURE (`videoquery.video_language`, owner: a Bengali video was shown
    as English): title script plus YouTube's language tag (one `videos.list` call, 1 unit). Never shown: any letter outside
    plain Latin/Devanagari (Bengali, accented Latin...), a tag that is not hi/en, romanised Hindi, Marathi/Nepali words in
    Devanagari. Hindi = Devanagari + (tag hi, or a Hindi function word); English = plain Latin + (tag en, or an English
    channel, or an English function word). (3) RANK BY SIMILARITY (`videoquery.scores`, code only, no embedding quota):
    the title (and a third of the description) against the story's words in the SAME language (headline weight 3 + half a
    point per mention in the article, max 4; inverse document frequency over the found titles), credible channels x1.1,
    newer wins ties; `PER_LANG` (5) each, max 2 per channel. Fewer than 3 kept -> filled with the best remaining
    sure-language videos even at zero similarity, so the card is empty only when nothing sure was found. Stored items carry
    `lang`; the site trusts it (`vlang`). Cost 200 units a story (400 with the older search) of 10,000/day (`DAY_UNITS`
    9,000), `limit` 6 stories a run. A story that found nothing is tried once more about 3 h later (`videos._due`). Needs
    `YOUTUBE_API_KEY`. Not run against the live API (no network or key in the sandbox).
    **Ongoing story + no Shorts (owner, Oct 13 2026).** (4) Headlines now avoid repeating earlier ones, so a follow-up's
    headline names only what is NEW while videos are titled for the whole story. `videos._thread` reads the story's earlier
    headlines from `story_links` (parents, their parents, nearest first, plus the root; at most `THREAD_MAX` 4; DB only).
    They go (a) into the same single phrase call (`videoquery.phrases(thread_en=, thread_hi=)`, `THREAD_NOTE`: write the phrase
    for the ONGOING event; `clean_phrase` accepts a word shared with an earlier headline and refuses an earlier headline's
    names) and (b) into the ranking words (`videoquery.document(thread=)`: floor `THREAD_WEIGHT` 2.0, so a video using the
    story's old words scores even though the new article never repeats them). Headlines of OTHER recent stories on the topic
    (`videoquery.neighbours`: share 2+ root words, last 7 days, at most 6) count only as a WEAK hint: a word counts
    (`NEIGHBOUR_WEIGHT` 0.75) only when 2+ of them share it, never in the search phrase, because another story's headline
    says nothing about THIS story's event. No extra YouTube or model call. (5) SHORTS are dropped first, before ranking and
    before the fill-up to `MIN_SHOW`: shorter than `videoquery.MIN_SECONDS` (90) or tagged #shorts (`is_short`). The length
    comes from `contentDetails` in the same `videos.list` call (`videos._details`, still 1 unit); a live broadcast ('P0D')
    or a failed details call means unknown length: kept unless tagged. More videos are now dropped, so the older no-date search
    (+200 units) runs a little more often.
  - **On the site: trial_version_2.1 (owner, Oct 9 2026; designed on the canvas, approved, built into site/index.html).**
    A plain interface published earlier without his asking was taken back the same night: never publish site/UI changes
    he has not approved. 2.1: a 30px menu button (the reader's initial once signed in) at the LEFT of the wordmark; the
    language switch and the article's back button and switch the same 30px (touch area 7px wider, `.hit`). After 7 s or
    two swipes the greeting fades and the language switch moves up beside the wordmark (`tidy()`): the header's height
    changes ONCE; the indigo (`#hbg`) is clipped up and the current card's top edge (clip on its slot) and content
    (transform) glide. Never animate the header's or the cards' height (scroll-snap makes the card jitter). Menu: Sign in
    / name + email, Sort (client-side, not remembered), Following / Read later / Daily recap / Search ("Coming soon"),
    Log out. Sign in card: name, email, password (log in: email, password); the session stays on the device (`np-me`,
    refresh token) until log out. Article: the colour bar flies from the card to under the headline (`flyBar`), then the
    colour names and the audio and video buttons. Audio card: sign in first; Hindi | English; 1 new audio a day; make or
    play; a player strip lights each sentence (`.sent.lit`). Video card: YouTube's order, Hindi first in turn, links out
    (needs YOUTUBE_API_KEY).
    **2.2 menu (owner, Oct 10 2026, canvas, approved):** everything needs sign-in. Following = one card: each section
    row a circle (follow all of it; light green gradient when on) and an arrow (its sub-sections), multi-select;
    States; Words and names (filters became follows: a word follow notifies when an article contains the word,
    `notify.word_in` over headline + text, English and Hindi, whole words, or a person the article names). Notifications
    = "My audio" (article, language, status) + every notification, unread count on the menu button. Daily recap = made
    at 11 pm IST, countdown, Notify me toggle (follow `recap|daily`), after 11 pm the articles and Listen. Search and
    Read later removed ("a news app, not Instagram"). Sort and Log out stay. The phone's back closes any open card.
    Sign in / log in show a spinner ("Signing in…") then a tick and "Welcome, <name>" before the card closes (owner, Oct
    10 2026: it looked frozen). The article page never scrolls sideways (`.sheet-scroll` overflow-x hidden, pan-y).
    Not built: share card.
    Skipped by the owner: "what changed since you last read", corrections log, outlet pages, perspective sorts. Not
    features (pipeline discussion later): search grounding for sources, transcripts as evidence, Embedding 2.

- **Design pass: one header, one shape, the colour rail (owner, Oct 15 2026; designed on canvases and a prototype, approved, in
  `site/index.html`, block "design pass" at the end of the first style block and of the main script).** The header is joined
  to the top edge (no floating card), full width, 15px bottom corners (the pills' curve), one indigo `--chrome-grad`
  (#1f2550 at the edge, #2b3570 at 98px + safe area, flat after) for the home header, the article's header and its pane;
  the sections bar mirrors it. Every control 30px fully round, every card 20px. **The article's header IS the home
  header** (`.chrome`: back | wordmark | language at exactly the home row's place; opening an article tidies the home
  header first); while the article grows out of the card the home menu pill folds into a back circle (`.cback`,
  `html.reading`). Under the header row hangs one indigo piece (`#cpane`, absolute, never pushes the article): the
  section names (`.cp.rr`, in as the article opens; `.rspace` keeps room for them; `#sheet.hasrail`) and the frozen pane
  (`.cp.pp`: the pin's bar, pills and definition, opened while the key card is out of view; the pin's own `on` class
  still decides, `.chrome.pinned` follows it). A tapped colour's definition carries a ‹ n/N › stepper (`paintStep`,
  `[data-gstep]`). **Every sentence in every section carries its wash** (tiles and quotes too; `SPOTSEL`). The reading
  line is replaced by **the colour rail** (`.crail`, `buildCRail`): one mark per sentence in reading order, coloured by
  grade, a gap where a section starts, the lines on screen lit; hold it for every section's name and a tooltip under the
  finger, drag to move, tap to go. The headline box stays white like the card (no indigo box). Card swipe motion and
  the card-to-article morph are unchanged. Use `headBottom()` / `pinnedTop()` wherever code needs where the header ends.
  The headline box stays white, so its picture ends before the headline (`.hbox.has-pic` padding 196px). `sw.js` np-main-43. Next (owner): face-aware picture crops for the cards and the article.

- **Pictures framed on their faces (owner, Oct 15 2026; `focus.py`, site block "pictures framed on their faces").** Card
  pictures were filled from their centre and cut most faces. At every feed export each picture the cards show is
  downloaded once (6 s, 4 MB), looked at and thrown away (linked, never copied, as agreed): OpenCV YuNet faces
  (`config/models/face_detection_yunet_2023mar.onnx`, MIT; score 0.6, a helmeted batsman scored 0.70; worked at 960 px,
  at 640 two people side by side were missed), else OpenCV's people detector with the head guessed at the top of the body
  (owner: "yes"; it can be wrong), else nothing (centre crop as before). Stored on the card as `img.fc` [[cx, cy, size],
  largest first, at most 6], `img.ar`, `img.fk` (face / person); cached per link in `focus.json` on the feed branch; at
  most 30 new pictures and 60 s an export; any failure gives no focus and never stops the feed. `opencv-python-headless`
  is pinned below 5 (OpenCV 5 dropped the people detector). Site: a card's picture is slid (object-position) so the faces
  sit 36% down its frame; faces that fit together are framed together; when they cannot, the card in view drifts face to
  face (6 s each, 1.2 s glide; home cards only, owner; still for reduced motion). The article's picture is framed on the
  group or the main face (42% down its 200 px box) and never drifts; `placeOverCard` starts the glide from the card's
  crop at that moment (mid-drift too), so nothing jumps. A picture can only slide, never zoom out below cover.
  NOT RUN on real outlet pictures (no network in the sandbox): tested on two photos and on stub feeds in the browser.
  `sw.js` np-main-44. **Follow-up (owner, Oct 15 2026: "works perfectly"):** the EYES sit a third of the way down the frame
  (card and article; `fc` gains a 4th value, the eye line from YuNet's eye landmarks; older entries: just above the face's
  centre); only FOREGROUND faces count (`focus.foreground`: height at least 0.45 of the largest and Laplacian sharpness at least
  0.3 of the sharpest of those, so out-of-focus background faces drop; main face first by size and sharpness); cache entries
  carry `v` (`focus.VERSION` 2) and older ones are looked at again. **Tilt (owner: "gyroscope aware"):** the card in view's
  picture moves up to 10 px behind its frame with the phone's tilt (`deviceorientation`, smoothed, the resting angle re-learned
  slowly, picture drawn at 1.07 so no edge shows, `html.tilt-on` once a sensor reports); off for reduced motion and while an
  article is open; iPhone permission asked once on the first tap. `cardPicNow` measures the crop inside the frame, so the opening
  glide still starts exactly where the tilted picture is. `sw.js` np-main-49.

- **The article's top in the card's order (owner, Oct 15 2026: the bar travelled down past the headline while the headline
  went up, and the opening jittered).** Now: the picture, the colour section straight under it (`#kcard` moved into
  `.hbox`, one white piece with the picture, as on the card), then ONE card of a different kind (`.hcard` + the lead
  `.paper.lead`): pale indigo paper with a fine indigo edge (`--leadbg`, `--leadedge`) instead of the white cards' shadow;
  its top row carries the card's kicker (`#hkick`, glides from the card's kicker like the headline: `--kx/--ky`) and the
  share button (upper right); the headline stays bold at the card's size; the lead in the headline's serif. The read-aloud,
  video and talk buttons follow the lead (`leadFirst`: moved inside `#rise`, so every `#rise` query still finds every
  sentence). The card's soft colour is the grade that colours most of the lead's text (`--leadc`, set in `leadFirst`; indigo until the lead is known). `sw.js` np-main-46.

- **Section cards: the even wash and the figures' layout A (owner, Oct 15 2026; designed on two artifact pages, approved).**
  (1) The numbered sections' text is justified, the last line of each paragraph left as it falls (tiles stay ragged). Their
  colour is no longer a background on each sentence: `washCard` paints a canvas behind each card (`.wcard`: essay, quote,
  tile, figure notes; not the lead): every sentence's line boxes grown by `WASH.spread` (15 px) on every side and blurred by
  `WASH.soft` (14 px), the colour its own `--sc` mixed into white at `WASH.tint` (14%); where two sentences overlap the
  colours mix by strength, so a colour runs under its neighbour's text with no seam ("C · even spread"). Painted after the
  opening glide (560 ms), one card per idle slot, cards in view first, again when a card's size changes; tapping a colour
  hides the layer (the old spot highlight takes over); the read-aloud's lit sentence draws on top. (2) "By the numbers"
  (`figuresHtml`, `figureOf`): square cards two to a row (square at least, taller for a long sentence), figure on top; an odd
  count opens with one wide card (number beside its sentence); a sentence with no figure goes into a plain card under them
  (it was a wide tile with no number). `figureOf` finds money, shares (ranges too), scale words, scores ("2-1"), labels
  ("BS-VII", "Phase II"), plain numbers (not years, not a date's day, a lone digit only when it counts something) and spelled
  numbers ("Fourteen", "A dozen"), shown as written. Every `.sent` now carries its `data-k` from `essayBody` (figures can be
  shown in another order than stored); `markSentences` keeps a key already given. `sw.js` np-main-48.

- **The home card in the page's order; headline and lead edge to edge (owner, Oct 15 2026).** The card's text was the first 9
  sentences in STORED order, so articles written before the new section order opened with Explained on the card while the page
  showed What happened. `feed.page_order` (the Python twin of the site's `pageOrder` / `sectionGroups`, same `SEC_ORDER`) and
  `feed._card_text(paragraphs, keys)` now take the paragraphs in the page's order; the Hindi card uses its own section keys, else
  the English ones. The site's fallback `cardText(paras, keys)` does the same (`ROW_SELECT` reads `sk` = section_keys).
  `FEED_VERSION` 4 rewrites every card at the next export. The card's text and the article's lead are justified like the section
  cards (last line as it falls). Headlines are NOT (owner, same evening: "some fit, others ugly due to uneven space"; 3-5
  large words a line): left-aligned, ordinary spacing, `text-wrap: pretty`. `sw.js` np-main-50. Test: `tests/test_feed_order.py`.

- **The back button is the menu pill's end; the pill folds into it (owner, Oct 15 2026).** `#back` was a solid white 30px
  circle (with the focus ring, 34px), while the menu pill's white end is a 24px segment inside a translucent 30px rim. Now
  `#back` is built like that end: the pill's rim (1px edge, `rgba(18,12,30,.34)`) and a white 24px centre (`#back::before`).
  The fold: the pill's right side slides left (clip-path on `.cpill` to 30px, and on `.mbtn` from 36px to a 24px circle), the
  menu icon / initial fades, the arrow fades in on the same centre. The article's header is opaque from its first frame and
  covers the home header, so the same fold also runs on a copy of the pill in the article's header (`.cfold`, filled by
  `syncFold()` from the home pill as the article opens); after 400 ms `#back` takes over. Closing shows the copy at once and
  it unfolds back into the pill. The copy sits right after `#back`, never last in `.crow`: `.crow > :last-child` is what
  right-aligns the language pill (appended last, it stretched the article's EN/हिं switch). `sw.js` np-main-51.

- **The home card's text has the section cards' wash (owner, Oct 15 2026).** Each card's `.text` becomes a `.wcard` and gets the
  same `washCard` canvas (spread 15, softness 14, 14%), painted only for cards on screen or next to it (`deckWash`,
  IntersectionObserver on the track, rootMargin one card) and only when the deck has been still for 250 ms (`washPump` waits:
  `paintDepth` tilts the slots mid-swipe, which would skew the shapes). `renderDeck` is wrapped (`setupDeckWash`), so a deck built
  again is painted again. The text box reaches into the card's 22px side padding (negative margin, same padding: the words do
  not move) and fades in over its top 14px, so the wash's soft edge is not cut straight. `sw.js` np-main-53.

- **Headlines fitted to the card (owner, Oct 15 2026; option C4 of the "Headline alignment" canvas).** After justified headlines
  (uneven spaces) and plain left (ragged), `fitHead` sets each headline's size from 3px below the usual (27px, Hindi 24px,
  24/22 on small screens) to 7px above, choosing the fewest lines with those lines nearest the full width (a lone last word
  costs extra); spaces are never stretched (`HFIT`, `hfitPlan`: canvas measureText with the element's own computed font,
  letter spacing included, cached). Lines are fixed as `span.hl` (block, nowrap). The article's headline (`#sheet-h`) is fitted
  at the card headline's width (`cardHeadWidth`), so the opening glide never re-wraps. Run on every deck build
  (`renderDeck` wrapped), every `fillSheet`, on resize and again when the fonts have loaded. `sw.js` np-main-54.

- **Optimisation pass (owner, Oct 16 2026: a screen recording of the opening, closing and refresh "at 10 FPS", the smooth
  background going sharp on refresh, the picture popping and a white rectangle over it).** Measured in headless Chromium
  at 4x CPU throttle on the real feed (stand-in pictures with the faces drawn where `img.fc` says). Causes and fixes:
  (1) `washCard` blurred each sentence on a scratch canvas, read every pixel back (`getImageData`) and mixed them in JS:
  100-800 ms per card, ~95% of the main thread while opening (3.3 s), closing (2.7 s) and refreshing (6.5 s), run in idle
  slots forced within 600 ms, so on top of every glide. Now each sentence's grown line boxes are filled in its colour with
  the canvas blur straight onto the card's canvas (no read-back; a later sentence is laid over an earlier one with the
  blur's alpha instead of the strength-weighted mix), at half a CSS pixel per canvas pixel (`WASH.res`; it is a 14 px
  blur). Same spread / softness / strength. JS while opening: 3.3 s -> ~0.17 s. (2) The article grew out of the card by
  animating `clip-path` on the whole sheet: main thread, a repaint of the article every frame, while the picture and
  headline moved on the GPU; when the page was busy they fell out of step (the white rectangle, the card flashing
  through). Now "one motion" (script block of that name): the sheet is never clipped; `#plate` (its background, white
  like the card, then the ground) grows from the card's rectangle by transform; the picture's frame and the image inside
  are animated together (WAAPI, `MORPH_STEPS` points on the eased path, frame stretched unevenly, image counter-stretched
  so it never distorts) from the card's exact crop and zoom (`cardPicNow`) to the article's; headline, kicker and bar on
  their own transforms, same 460 ms and curve, all started on one frame; closing runs the same path the other way with
  the same fast-then-settle curve. The start is drawn once before anything moves (`nextFrames`), the article's picture is
  waited for (`picReady`: it was created fresh at each opening and was not loaded yet, so it never morphed and sat at its
  final size from the first frame: the "wrong crop" pop), the sheet is shown only once its start frame is built, and an
  article arriving mid-glide is filled in after it. `fitPic` frames on the story the picture belongs to
  (`hpic.dataset.sid`), so closing (openId already null) keeps the face framing. (3) `.rspace` (room for the section names)
  grew its height for 560 ms after the glide: a relayout of the whole article every frame and the article sliding down
  56 px after landing. It is now there from the first frame, never animated. (4) Refresh rebuilt every card even with
  nothing new, throwing away the painted washes ("went sharp") and freezing for 1.3 s: `renderDeck` returns "same" for an
  identical deck (signature `track.dataset.sig`: language, ids, times, headlines, pictures, bars, text length) and only
  updates the "x min ago"; a rebuilt deck washes the card in view and its neighbours at once (`washDeckNow`). Results at
  4x throttle: opening JS 3.3 s -> 0.17 s, the glide itself at 60 fps (frames every ~16 ms); closing 12 -> 50+ frames in
  700 ms; refresh worst frame gap 1350 ms -> 33 ms. Left: ~150-230 ms (4x; ~50 ms on a phone) between the tap and the
  first moving frame, the browser laying out the whole article for the first time. NOT verified on a real phone.
  **Owner's design changes, same day:** the glow above the card's colour bar (`.aglow`) is gone; the blur at a picture's
  foot is a short band (card: sharp to 76%, fade to 94%, wash from 74%; the article's picture fades from 80%; the
  article's opening copy uses the card's stops so the glide starts from exactly the card). **Close-ups framed
  ("portrait photos", owner):** every feed picture is landscape; a close-up's eyes sit 40-55% down and the card's picture
  fills its frame's height exactly, so it could not slide up and the face ran into the fade. `zoomFor` zooms such a
  picture in just enough to bring the eyes to their line (at most `ZOOM_MAX` 1.6, never past a face `ZOOM_FACE` 0.6 of the
  frame; pictures whose eyes already sit at or above the line are not zoomed, so wide shots are unchanged). Card: slid by
  object-position at cover size as before, zoomed by `scale(var(--z))` about the point that lands the eyes on the line
  (it joins the blurred copy's 1.15 and the tilt's 1.07; its origin glides with the drift); article: laid out at the
  zoomed size. **Tall photos (owner, same evening: by "portrait" he meant a vertically long, full-length photo, e.g. a
  cricketer playing a shot):** none were in the feed, so tested with stand-ins. With a face or body found they framed
  correctly; with nothing found (a helmet, a side-on stance: the case such photos hit) the picture was centred, which on
  a tall photo is the chest, so the head was cut off on the card and in the article. `tallGuess`: a photo more than 5%
  taller than wide with no focus is framed as if its eye line were `TALL_EYES` (12%) down, i.e. from the top (card: once
  its image has loaded and its shape is known; article: in `fitPic`). `sw.js` np-main-56. Harness (not in the repo): Playwright, `Emulation.setCPUThrottlingRate` 4, rAF gaps,
  long tasks, a CPU profile and the screencast frames of open / close / refresh.

- **No white flash; dropdowns close smoothly (owner, Oct 16 2026, a phone recording).** (1) Opening: on the phone the sheet
  showed for ONE frame before its start position reached the GPU (the plate full-screen white, the header not drawn yet).
  Now the morph's first keyframe is also set as plain styles (`holdStart`, cleared by `stopMorph`), the sheet is first
  drawn at 0.01 opacity (`#sheet.pre:not(.anim)`) so its layers are rasterised while the card still shows, and the
  plate's white goes in 220 ms. (2) Closing: the article text left at once while the white plate covered the card, whose
  text came back only at the end (a blank white card). Now the plate fades out first (`#sheet.leaving #plate`), the card
  stays visible under the glide with only its picture, headline, kicker and bar hidden (`a.card.under`), and at the end
  the two hand over in a 130 ms crossfade (`#sheet.gone`, `releaseUnder`). (3) Dropdowns (Sources, Who reported what):
  at the article's foot a closing list makes the browser pull the page down, all at once and late (measured: 144 px in
  55 ms; for the long list the heading still 0.3 s, then 618 px in 0.25 s). Closing now takes 440 ms on an ease-in-out
  curve, the list fades over its first half, and `ddFollow` moves the page itself on the same curve (a spacer at the end
  stops the browser's own pull). The tap's ring (`ddWave`) was sized to the whole card, a ~3,600 px circle on the long
  list that held the page for 0.3 s: now sized to what is on screen. `sw.js` np-main-62. Tested in the throttled
  harness, not on a phone.

- **Dragging the colour rail (owner, Oct 16 2026: "the scroll needs to be smooth; the bar under my finger in the middle of the
  popped ones, 2 above and 2 below; the sentence I select at the centre of the screen; not at the bar's ends").** It jumped
  the page (no animation) to put each line at the TOP, and the popped marks were the lines on screen (measured: 1 above the
  finger and 4-6 below, the line ~257 px above the middle). Now (block "the colour rail", the drag handlers): the line goes
  to the middle of the visible part under the header (`centreOf`; as far as the page allows at its ends), the page glides
  there with one follower that only changes its target as the finger moves (`glideTo`, exponential, ~0.25 s; a touch on
  the article stops it), and the popped marks are the finger's and `POP` (2) on each side, slid inwards at the rail's ends
  (`popAround`, class `pop`; the on-screen `inview` lights are neither updated nor shown while dragging). The nearest mark
  is found from positions cached relative to the rail (`segAt`, refreshed when the rail's height changes as the header's
  pane opens). A tap glides to the line and centres it too. Measured: 2/2 popped in the middle, the line within 2-20 px of
  the centre. `sw.js` np-main-63.

- **No flash at the end of closing (owner, Oct 17 2026, a desktop recording: the colour bar and the picture flashed white, some
  headlines snapped to another size).** (1) Bar: `flyBarBack` reset the article's bar after a fixed 500 ms, while the sheet was
  still fading, so it jumped back to its place in the article for a few frames. Now `resetBar()` runs only once the sheet is
  hidden (end of `closeStory`, the no-animation close, and the start of `openStory`). (2) White dip: the card's picture,
  headline, kicker and bar faded in (130 ms) while the sheet faded out, two half-transparent copies over white. The card's
  copy now appears at once under the sheet and only the sheet fades. (3) Headline snap: at 700 px and wider the card's
  headline base is 32px but the article's was 27px, so `fitHead` fitted them to different sizes and lines (17 of 30 cards
  at 900 px). `.hbox h1` is 32px there too: 0 of 30 differ at 900 px and on a phone. Checked in the throttled harness at
  both widths, not on a real phone. `sw.js` np-main-64.

## Pipeline (nishpaksh/run.py)
ingest RSS → proactive search (`discover.py`: Google News decoded, Bing; Tavily fallback) →
retract headline-only reads → Tavily reads blocked pages → wire copies → grouping (`stories.py`) →
read articles (`extract.py`, Flash-Lite) → per story: match statements → consolidate
(`consolidate.py`: merge duplicates, contradictions, one spelling per name, who says what) →
perspectives → origins + fact/characterisation → verdicts (`verify.py`) → settled? (`editions.py`) →
colours of published articles mature → retention → health checks in `runs.stats.health` → (workflow
step) articles older than 3 days to the archive branch. Rating (`priority.py`) comes after grouping;
search, Tavily reads, reading and analysis cover the preparation queue only.
Settled = (`editions.settle_decision`, first that holds) the 8-hour cap since the publishing rule was met, OR 3 quiet hours
with no new independent outlet, OR (owner, Oct 11 2026: "either the rule got satisfied or X articles have been
collected") BROAD coverage: `settle_early_outlets` (8) INDEPENDENT outlets (`wire.independence_groups`: wire copies, one
owner and state media count once; not raw articles, so ten reprints of one wire story are one) and the rule met at least
`settle_early_min_minutes` (60) ago, so the first wave of a burst has landed. 8 is above the publishing rule (about 3) and
above `global_min_sources` (6, where a global comparison starts). `settle_early_outlets = 0` switches it off. A story
closed early is never changed; later outlets gather in a follow-up candidate, which must clear the follow-up bar. Old
news (newest source over 36 hours) is never written. `runs.stats.settled_broad` counts the stories ready ONLY because of
the broad rule: raise X if follow-ups pile up behind early articles, lower it if it is always 0. NOT RUN ON REAL DATA: the
decision is tested as a plain function (no store).
Writing desk (`desk.py`, after the pipeline in the same job): settled stories, most important first → follow-up? → page, written once
(`compose.py`: threads, the news; `narrative.py`: the essay led by the news; `news.py`: headline) →
Hindi. At most 2 per clock hour.
A held essay says why (owner, Oct 11 2026, story 16981: "carries 36 statements, short of the bar" named neither the check nor the
total): `narrative.essay_shortfall` gives {why, model, covered, total, need, sentences, rejected} with the same tests as
`essay_ok` ("no essay", "most sentences rejected", "coverage" under 85% of every statement, or "writer model not
allowed" added by `compose`). It is logged ("short of the bar (why): X of Y statements covered, Z needed ..."), kept in
`stories.analysis.writer_failures.shortfall`, and listed per story in the desk stats as `short`. The writer's premium Flash
models have `rpd: 20` a key (`models.yaml`), so a draft's fill passes often fall to 3.5 Flash-Lite; a held draft is resumed
next hour. The length cap in `narrative._target_length` (50 sentences, up to 66) only blocks the 85% bar above about 77
statements. NOT RUN ON REAL DATA: `essay_shortfall` is tested against `essay_ok` for every size up to 120 statements.

## Known quotas and facts learned from real data
- Google counts **each text in an embedding batch** as one request: ~1,000 texts/day per key.
- Flash models: 20/day each per key (writer/judge); Flash-Lite 500/day each per key; Gemma is
  unreliable on the free tier (overflow only). Grounded search ~20/day per model per key.
- **Refused (503) calls appear to count against Google's daily limit** (Oct 5 2026: gemini-3.6-flash
  key 1 had 0 successes all day and got Google's own per-day 429 after 13 refusals). A model refusing
  3 times in a row (any key) is dropped on every key for the run (`router.OVERLOAD_STREAK`), and the
  tier moves to its next model. Our counter still refunds refused calls; Google's 429 is the real limit.
- Quotas reset at 00:00 Pacific = 12:30 IST. **Every tier is paced** over that day
  (`router.pace_fraction`: hours weighted 1.5 on 07:00-23:00 IST and 0.5 at night, plus 2 h
  slack; unused carries forward): unpaced, Flash-Lite ran
  out after ~15 runs and the site sat frozen from ~23:30 to 12:30 IST (Oct 4-5 2026). Dispatch the
  hourly workflow with reason `backfill` for a deliberate unpaced catch-up.
- `light` = analysis (decides colours); `page` = headline, importance, threads, Hindi (same models,
  nothing kept back, so page building is never the step starved). Before moving a light/page task
  to another model, run `tools/modelcmp` (workflow `modelcmp`).
- Health flags a tier that cannot pay for one call (embed < one 25-text batch) and grouping that
  stalls for 3 runs while articles keep coming in.
- Run logs are readable via the `runs` table (stats + health). A crashing run writes its traceback to
  `diagnostics` (kind 'crash'). `gh run list/view` shows run status, but job log downloads were refused
  (403) from the sandbox; tools write to the `diagnostics` table instead.

## Tools
- `python -m nishpaksh.tools.replay --stories 10192,10254` (workflow `replay`, dispatch via
  Supabase `net.http_post` with the Vault token): re-run writing stages on stored stories, site untouched.
- `python -m nishpaksh.tools.modelcmp --variants flash,flash2,gemma`: same stories analysed from
  scratch per model; per-statement colour confusion vs Flash-Lite's own run-to-run noise.
- `python -m nishpaksh.tools.probe --parts search,fetch,grouping,embedcmp`: measurements on real data.
- Tests: `python -m pytest -q` (fake backend in `tests/fixtures.py`; add fakes for any new prompt).

## Open items
- **"Could not ask" is not "no" (Oct 25 2026; the engineering track of the Notes, shadow-mode rule: a new system replaces code only
  after it beats it on stored data).** (1) `match.same_facts` / `covers_facts` return `bool | None`, `check_conflicts` `str | None`:
  None = the model could not be asked (quota, error, missing item, second asking failed); `consolidate` and `disputes.judge` cache only
  real answers and ask the rest again next run; old "unsure" conflict answers were purged once (`analysis.conflict_checks_v` 2).
  (2) Archive unreachable (Group A, H95: 1 of 7 follow-ups lost its parent): `pagearchive.fetch_page` / `recent_index` no longer cache a
  failure (it hid the page for the whole run and marked the thread check "done" with no archived candidate seen); `strict=True` raises
  `pagearchive.Unreachable` for a network error or non-404 status (a 404 = "no such page", still an answer); `compose.build_payload`
  and `threads.find_parents` use it and `publish_story` answers "parent unreachable" (a skip: no try, no refusal), so a follow-up is
  never closed without its thread or without the follow-up check. After one failed request the archive counts as down for 120 s
  (`DOWN_SECONDS`), so a run pays one 15 s wait, not one per story. Tests: `tests/test_unanswered.py`, `tests/test_archive_unreachable.py`.
  **Group A numbers (14 days, 65 stories, `ledger`-style audit, Oct 18):** 98% of statements "unverified" (37 corroborated, 3
  developing); half the stories have 1-2 independent sources (express); perspectives never qualified (positions test false on all 16
  days); full name written 3+ times in 49% of articles (no person evidence 29, shared surname 22: the entity table's evidence);
  speaker key = surname collides for different people in ~4 of 42 stories (Banerjee, Singh, Yadav; the other 10 flagged are one person
  under two spellings of the title); the person detector rejects real speakers whose name carries a title ("Canadian Prime Minister
  Mark Carney", "MK Stalin"); repeated sentences are about 6 of 65 articles (the detector's 11 includes different-subject pairs such as
  India's and Pakistan's scores); a stampede dated Saturday 17 and Sunday 18 October stood as two plain facts (no dispute, no merge).
- **Entity table, SHADOW (Oct 25 2026; `entities.py`, `tools/entities_shadow.py`, workflow `audit` tool `entities_shadow`; Notes B1/B2/B18).**
  One identity per person in a story, by code: `parse` splits a mention into title and name (name = trailing capitalised words, stopped by a
  title word); same name through `spelling.key` = one; a longer name absorbs a shorter one that is an ordered part of it (initials fit
  words that start with them); two written-out first names that differ are never linked (Bhim vs Harjit Singh); a lone surname that fits
  two people stays ambiguous. Person evidence is per ENTITY, not per string: a title, a speech verb, being a quoted speaker, an age, a
  passive only a person can be ("was arrested", "died"), or an occupation apposition; countries, teams, films and schemes get none and are
  never shortened (teams "scored / won" are deliberately NOT evidence). `EntityTable.speaker_key` (entity key for a person, the old key
  for bodies) and `.shortenable()` (a surname no other name in the story has as ANY word) are what would replace `voice.speaker_key` and
  `style.people`. NOTHING CALLS IT YET: run the audit workflow with tool `entities_shadow` and read `diagnostics` kind 'entities_shadow':
  `split` (one old key, several people), `merged`, `gained` / `lost` shortened names (every `lost` is a possible regression), `weak`
  (gained names with only age / passive / apposition evidence: are they people?). Adopt only if `lost` is empty or explained and `gained`
  names are people. Tests (real Group A names): `tests/test_entities.py`.
- **The test suite is green again (Oct 16 2026, session 1 of the translation/learning plan).** It had failed on every one of the last
  60 runs: 17 Python tests and 4 Node files lagged behind the owner's own later commits (section order, intro words and live-intro
  keys, grammar wording, two beat seats, `who` on pages, the guide saying the intro itself, `playbackRate`). They were updated to
  the decisions above, each with a comment naming the change. Three were real bugs, fixed: (1) `people._clean` / `_ok`: since the
  titles registry "Supreme Court" / "Election Commission" were cleaned to nothing / "Commission" (their words are title words), so
  readers following them got no notification; a phrase ending in an institution word (`people.BODY_END`) is a body and keeps its
  name; (2) `desk.work`: with two beat seats, "empty" for the second seat overwrote the list of who took the first; now
  `beat_seat` keeps the list and `beat_seat_empty` says how many stayed empty (ledger reads both); (3) `talk.js` `end()` did not
  wake a start still waiting for the server or the intro (it returned 15-30 s later). The Node controller tests now start, then
  open the fake socket (`openReady`), since `start()` returns only after the intro; their fake server ends the intro turn itself.
  **Clock part fixed:** `test_end_to_end` failed from 18:30 to 24:00 UTC (IST already the next day): the headline the fake
  wrote carried the news line's "(dated: ...)" note; the fake now strips it and the assertion accepts either lead fact.
  **Still open:** with `PYTHONHASHSEED=7` at night it fails with KeyError 'A section of the Kesarganj flyover collapsed'
  (a merge upstream depends on set order). Not yet traced.
- **The Translator key is reserved for quality work (owner, Oct 16 2026; its own Google Cloud project).** Secret
  `GEMINI_API_KEY_4` (add it on GitHub; passed in hourly.yml). `models.yaml` `keys:` names which tiers a key may serve:
  a key named there serves ONLY its tiers, and a tier named there is served ONLY by its keys (`router.Router.allowed`).
  The new tier `quality` (Flash-Lite models) is served by key 4 alone; without the secret, `quality` is empty and a call
  raises QuotaExhausted (nothing else falls back to it). Usage keys carry the secret's suffix (`@k4`), never the position,
  so quota counts stay right whichever keys are set (`config.gemini_key_name`). Nothing calls `quality` yet: it is for the
  translation and fidelity work of the next sessions. Tests: `tests/test_key_reservation.py`.
- **Dates and times read by code (Oct 16 2026, session 2 of the translation/learning plan; `when.py`, no model).** The
  reading model used to turn time words into dates itself ("Tuesday night" + the publish time -> start/end): the model
  typing a value. Now it only copies the words (`when_text`) and `when.read_time` places them, counted from the report's
  publish time (IST): dates in any form and both languages ("October 15", "Oct. 15, 2026", "15th of October", "15/10/2026"
  day first, "15 अक्टूबर", Devanagari digits), ranges ("17-22 October", "from October 17 to 22", "17 से 22 अक्टूबर"),
  weekdays (the last one on or before the report, the next one for a statement in the future tense), relative days and
  weeks / months / years ("yesterday", "last week", "आज", "परसों"), clock times (IST only: "local time" or another zone
  keeps the day and drops the hour) and parts of the day. A date with no year takes the nearest year; a clear tense
  (`when.tense`: future words and no past ones, or the reverse) keeps a past event before the report and a future one
  after it, and a year so chosen more than `FAR_DAYS` (300) away is refused. NEVER GUESSED (-> None, the model's date
  stays): a weekday or "कल" without a clear tense, a weekday that contradicts its date, a clock time with no day, a
  festival name, two dates ("October 2022 and February 6"; a day/month with a year given apart is one: "December last
  year"), and bounds or parts code does not model (`BOUNDS`: before, after, until, since, between, around, and, or,
  overnight, quarter ended, early, mid, weekend, ago, तक, के बाद ...). First audit of code's first version on 20,000 stored
  statements (6,830 with time words): agreed 5,159, differed 133 (most of them code's own mistakes, fixed by these
  refusals; some the model's: "Tuesday night" put on a Wednesday), model alone 310, refused 10. Code's reading replaces the model's (`time.by = "code"`); the model's date is kept only when code cannot read
  the words (`by = "model"`), and refused when it puts a past event more than an hour after publication. Counted in
  `runs.stats.when` (code_agrees, code_differs, model_only, model_refused, none). New precision "year". One date reader:
  `frames.date_of` (so relate, disputes) is `when.date_of`; `compose.drop_past_schedules` reads dates through it (nearest
  year, never the tense's: the line itself says "will"); `narrative.english_when` turns Hindi time words into English.
  **House date form "15 October" (day first) in what WE write** (`when.house_dates` in `style.polish`, every sentence and
  part, and the headline; never inside a quotation): the audit found both forms in 57% of mixed-language articles.
  Outlets' statements are compared by value and stay as written (the figures rule). `when.date_values` gives the dates a
  translation must keep (for the fidelity work). The audit (`tools/audit.when_report`) compares code's reading with the
  model's on the newest 20,000 stored statements. Tests: `tests/test_when.py`.
- **The name registry (Oct 16 2026, session 3 of the translation/learning plan; `names.py`, table `name_pairs`).** Each
  part of a name (Rahul, Sharma, Rimpochee) in English and Hindi. The owner's rules: EXACT spelling only, no similarity
  ("Shrma" is unknown, not "Sharma"; Hindi variants of the same letters, गांधी / गाँधी, ज़ / ज, are counted as one and
  shown as most outlets wrote them); both spellings are COPIED from outlets that covered the same story (learned only
  where a story has Hindi and English sources); per language the spelling most independent sources used wins; a pair is
  "attested" with 2+ independent English sources, 2+ independent Hindi sources and 2+ stories, else "seen" (usable,
  low trust); a full name is split into parts only when both sides have the same number of parts. Sources are
  `names.source_key` (agency byline, else wire group, else owner; state media never counts), stable across stories.
  A part no outlet pair covers is transliterated by one batched call on the `quality` tier (Translator key only),
  validated (one part in the target script, no echo) and stored as "translated" until outlets show their own
  spellings; no quality quota = the part stays unknown, never an error. `config/names.yaml` holds the owner's own
  pairs and the state names of `places.py` seed the registry; both always win. Two attested Hindi forms for one
  English part are flagged (`Registry.conflicts`), never overwritten. `english_spelling` gives the spelling English
  outlets use most for a variant, linked only through a Hindi word OUTLETS paired with both (never a transliteration).
  Nothing in the pipeline calls it yet: session 4 pairs a story's names before reading and gives the reading model the
  stored spellings; the Hindi page uses the Hindi forms later. **Supabase holds reader tables only:** `Store.init(only)`;
  the readers' database and the gate (`runs`) create and check READER_TABLES alone, so a new newsroom table can no longer
  stop the run or the gate, nor take Supabase space. `name_pairs` is in `TABLES` in `newsroom.sh`. Tests: `tests/test_names.py`.
- **Names paired before reading (Oct 16 2026, session 4 of the translation/learning plan; `namepair.py`).** In
  `extract.extract_pending`, before the reading threads start (they run in parallel and in no order), for the
  articles chosen this run: (1) LEARN, stories with English and Hindi articles: the English names are read by code
  from the English outlets' text (people.py's capitalised names; titles, bodies ending in an institution word,
  acronyms and a trailing kind-of-place word such as "Airport" taken off: Hindi translates those), and from the stored
  statements of English articles read in earlier runs (their text is not fetched again). A name whose stored Hindi
  form appears word for word in a Hindi outlet's text is confirmed with no call; the rest go to ONE closed question
  on the `quality` tier, asked twice with the names in reverse order: "copy the words this Hindi report uses for each
  name, or NONE". THE MODEL POINTS, IT NEVER TYPES: an answer counts only when both askings give the same string,
  it appears verbatim (whole words) in a Hindi outlet's text, has as many words as the English name, and no other
  name got it. Each pair is stored part by part in `name_pairs` with the source keys of the outlets whose text holds
  each spelling. At most 8 stories asked per run. (2) HINT, every Hindi article: runs of up to 4 Devanagari words the
  registry knows (exact lookup) go into the reading prompt's NAMES block ("रिम्पोछे = Rimpochee"), so a Hindi
  outlet's statement spells names as the English outlets do before matching. No quality quota, a refusal or any
  error: reading goes on exactly as before (`prepare` never raises); consolidate.py's spelling step stays the
  backstop. Logged as "namepair: {confirmed, asked, agreed, pairs, hinted}". Tests: `tests/test_namepair.py`.
- **Fidelity checks (Oct 16 2026, session 5 of the translation/learning plan; `fidelity.py`, `config/glossary.yaml`, no
  model).** The small words that change what a sentence claims are listed by hand in both languages (glossary
  `qualifiers`: negation, never, directly, only, at least, up to, more than, alleged, specific; and, counted only until
  the numbers show they are not noisy, `strict: false`: approximately, hedges, reportedly; `number: true` ones count
  only next to a number, "about 40" not "about the case", and are compared NUMBER BY NUMBER: "over 75,000" is
  lost only from a statement that carries 75,000; Hindi scale words read as numbers, 3,350 करोड़ = Rs 3,350 crore).
  A reading or a translation must keep each one its source has and add none it lacks; for a READING, a qualifier
  counts as lost only when the statement says what it is about (English source: the words after it are in the
  statement; Hindi source: its clause holds one of the statement's anchors), so a statement taken from part of a
  sentence keeps only its own part's qualifiers (the Rahul Gandhi case: "directly" lost, "specific" added). The source sentence a
  statement came from is found by ANCHORS ONLY: numbers by value in any script, dates (when.py), names exactly (Hindi
  through the name registry) and the glossary `entities` (BJP / भाजपा, used only for this, never to choose a word). The
  old consonant-skeleton tie-break is not used (it made सीधे match "side"); no sentence or a tie = nothing checked.
  `latin_left` finds Latin words left in a Hindi string (not URLs, units, or a bracketed name the English also brackets);
  `missing_terms` finds our binding Hindi renderings (glossary `terms`) not used. Nothing acts on a problem yet: the
  English->Hindi path (session 6) and the reading path (session 7) do. The audit reports it on stored data
  (`tools/audit.fidelity_report`: live pages' Hindi strings, statements of the newest 600 read articles). Tuned over
  four audit runs on stored data (Oct 16 2026; each noise case is now a test): "alleged" only as an adjective and an
  attributing verb (alleged, claimed, आरोप) keeps its caveat; विशेष and निश्चित are not "specific"; "not out", "या
  नहीं", "सीधे सेट" are not qualifiers; Hindi "never" is कभी ... नहीं around the verb; "100% तक" is up to, "15
  अक्टूबर तक" is not. Last run, strict problems: about 30 of 1,737 live Hindi strings; 18 of the 287 Hindi-report
  statements whose source sentence was found (of 1,171: most share no anchor with one sentence); about 120 of 2,277
  English-report statements. Real catches among them: "only 45 of 303 stations" and "only 14 of 4,600 seats" read
  without "only", "the only authorized protest sites" where the report said designated. Known misses: negation
  by morphology ("unaffected" / "प्रभावित नहीं"); a statement matched to the wrong sentence of a long report.
  Tests: `tests/test_fidelity.py`.
- **The Hindi page, Translator's way (Oct 16 2026, session 6 of the translation/learning plan; `hindi.py`).** In
  `compose._translate`, per batch of 40 English strings: (1) the people and places in them (namepair.english_names, no
  titles, bodies or acronyms) are looked up EXACTLY in the name registry; parts no pair covers get one transliteration
  call on the `quality` tier and are stored; the batch prompt lists the names used ("Vats = वत्स") and our binding terms
  (glossary `terms`) the batch uses, nothing more. (2) The draft on the `page` tier, as before; the prompt now asks for
  names of people and places in Devanagari and abbreviations the way Hindi newspapers write them (BJP = भाजपा, ITF =
  आईटीएफ; the owner's call on organisations was pending: this follows Hindi newspapers), the formal news register,
  natural Hindi word order, and keeps the small words (fidelity.py). (3) Code replaces a known name left in Latin
  letters by its registry form (whole words, longest first, never inside brackets: refs.py keeps those on purpose).
  (4) The checks: `translation_problem` (hard: empty, echo, numbers, brackets, pronoun) and
  `fidelity.check_translation` (small: qualifiers, Latin left, terms). (5) The EDIT pass, Translator's second pass:
  every batch, on the `quality` tier (Translator key), English and draft side by side with each string's problems
  named; an edited string replaces the draft only if it has no hard problem and no more small ones. No quality quota:
  the draft stands. Strings with a hard problem are never cached (English shows, the page stays "partly translated",
  `finish_translations` retries); a small remaining problem keeps the better version, cached. **Cache key** carries
  `hindi.cache_version()` (a hash of our binding terms): changing a term translates again; the deploy itself started
  a fresh cache (old rows stay, unused). **Names mend old pages:** every render (`translate_payload`,
  `translate_strings`) replaces Latin names in cached Hindi with what the registry knows now, at no cost. Logged per
  page as "hindi: {strings, drafts_with_problem, edit_calls, edit_accepted, names_known, names_translated, ...}".
  Tests: `tests/test_hindi.py`.
- **Readings checked against their reports (Oct 16 2026, session 7 of the translation/learning plan; `readcheck.py`).**
  The reading prompt's rule 2d asks to keep every small word that limits a claim (not, never, only/केवल/सिर्फ/महज,
  at least/कम से कम, up to, more than/से अधिक, directly/सीधे, alleged/कथित) and add none. In `extract._extract_one`,
  after `ground()` and the dates, every statement (English and Hindi reports alike) is checked by
  `fidelity.check_reading` against the sentence it came from (strict qualifiers only; negation not compared for a
  "denies" statement, which rule 4 writes as the positive claim). An article's flagged statements get ONE repair call
  on the `quality` tier, each shown with its report sentence and problem; a repair is taken only when the check then
  passes and the statement keeps its numbers. At most `MAX_CALLS_PER_RUN` (30) repair calls a run; no quota = nothing
  repaired, nothing waits. An unrepaired statement is KEPT and counted (`DROP_UNREPAIRED = False`): the audit showed
  real catches beside wrong-sentence matches, so dropping waits for the counts. Logged as "readcheck: {checked,
  sourced, flagged, repaired, kept, calls, no_quota, over_cap}". Tests: `tests/test_readcheck.py`.
- **Matching across written forms (Oct 16 2026, session 8 of the translation/learning plan; `relate.py`).** The audit
  showed the same fact left as two statements far more in mixed-language stories (11.6 near pairs per 100 statements
  vs 6.1), while repeated sentence openings were rare (1.7% / 3.9%; runs of 3+ in 6 of 102 articles), so session 8
  fixed matching, not the writer. (1) Currency words (Rs, INR, rupee/rupees) are neither names nor words to compare:
  "Rs 375" = "375 rupees" (story 26318). (2) A name one line capitalises and the other writes in lower case is the
  same name ("Divyangjan Pension Scheme" / "divyangjan pension scheme"). (3) Clock times (when.find) are times, not
  figures or names ("12:30 PM" had added 12, 30 and a name "PM", the Ladakh pair): two different times = different
  facts; a time only one line has is a detail, so code never lets the untimed line stand for both and asks the model
  whether the timed line covers the other. These also reach `narrative._drop_repeats`, the last net on the written
  article. Joining parallel sentences ("Modi will inaugurate X, Y and Z"): built in context plan session 7 (below). Tests: `tests/test_relate_forms.py`.
- **The learners' base and the titles learner (Oct 16 2026, session 9 of the translation/learning plan; `learning.py`,
  `learn.py`, `config/devils_advocate.yaml`, `.github/scripts/learn.sh`).** The learned files stayed empty because each
  run counted from scratch inside a 3-day window. MEMORY: `learn_candidates` in the NEWSROOM (never Supabase, never
  the public repo; in `TABLES`): per candidate its independent sources (`names.source_key`, the same in every story;
  state media never counts), stories, days, the articles already counted (a re-read adds nothing), learner facets,
  status (candidate / proposed / learned / blocked), the devil's advocate's verdict and reason; forgotten after 30
  days without new evidence unless decided. `learning.Bar` (sources, stories, days, max one-day share, probation) and
  `funnel` (where candidates stop, logged). DEVIL'S ADVOCATE: only holds or blocks, never approves; code cues
  (devils_advocate.yaml: label words, dispute/insult words, `never_titles`, English and Hindi); a model look at most
  once a day per learner on the quality tier, asked twice with the choices swapped (`learning.ask_twice`), only to
  block or hold. TITLES (`learn.py`): sightings of a word mid-sentence before a quoted person's full name in English
  articles; bar 3+ sources, 3+ days, no day over half, 7 days of probation, 2+ people, 1+ wire agency or foreign
  outlet, also used in lower case. Code advocate: never list, loaded word, over 70% of sightings before ONE person
  (the owner's "Pappu"), label cue in over 20%, insult/dispute word near in over 10%, mostly quoted (hold). Then the
  model's "title held or label?" NEVER learned automatically: written to `config/titles_proposed.yaml` (words, people,
  counts; no article text), rewritten each run; the owner APPROVES by moving the line to `titles_learned.yaml` `roles:`
  and REFUSES via `rejected:`; `review:` lists approved titles the advocate now objects to. One job script `learn.sh
  <name> <module> <files>` (learn_titles.sh removed). Logged "title candidates: {funnel}". Tests:
  `tests/test_learn_titles.py`.
- **The synonyms learner on the base (Oct 16 2026, session 10 of the translation/learning plan; `learn_synonyms.py`).**
  Same evidence as before (two claims under one model-merged statement, from different independent sources, the same
  words but for one, not already "same" to code), now ADDED UP across runs in `learn_candidates` (kind "synonym").
  Bar, the lightest: 2+ independent sources, 2+ stories, 2+ days with no day over 70%, 3+ merged statements. Devil's
  advocate: evidence against REMEMBERED FOR GOOD (both words in one statement; the swap between contradicting
  statements); `never:` / `rejected:`; a word that limits a claim (fidelity glossary qualifiers); a word a reading
  tagged loaded; FRAMING SPLIT (hold) while no source has used both words (per-source word use and both words in one
  article are recorded); the model's look once a day ("same meaning or changes stance/degree/certainty?", asked twice).
  Learned AUTOMATICALLY (owner, Oct 14 2026), at most 5 a run, appended to `synonyms_learned.yaml` (counts only, no
  sentences: the example field is gone); a learned pair the advocate later blocks is taken out of the file
  (`withdraw`). The job runs through `learn.sh` (learn_synonyms.sh removed). Logged "synonym candidates: {funnel}".
  Tests: `tests/test_learn_synonyms.py`.
- **English-Hindi terms learned from the outlets (Oct 16 2026, session 11 of the translation/learning plan;
  `learn_glossary.py`, `config/glossary_learned.yaml`).** Evidence only from Hindi and English OUTLETS on the same
  stories, never our own translations (a repeated mistranslation would look like evidence). Per story with 2+
  independent English and 2+ independent Hindi sources: English lower-case words 2+ English sources used, Hindi words
  2+ Hindi sources used that the name registry does not know; stop words out. A pair counts in a story only when the
  two words stand in an English and a Hindi SENTENCE that share a number (10 or more, by value, any script): story-
  level pairing paired words that merely share a story ("rolls = ज्ञानेश", "shipping = ईरान" in the first replay, Oct
  16 2026; that memory, kind "glossary", is deleted; the aligned memory is kind "glossary2"). Across the window's
  stories: a pair in 2+ stories, Dice >= 0.6, each the other's single best partner, no tie, neither in over a quarter of the stories
  (with 8+ stories). Such pairs add their stories to memory (`learn_candidates`, kind "glossary"). Bar: 2+ English
  and 2+ Hindi independent sources, 3+ stories, 3+ days, no day over half. Devil's advocate, CODE ONLY (no model):
  blocks a loaded English word, a fidelity qualifier, a Hindi dispute/insult cue, the owner's `rejected:`; sends to
  the OWNER (`proposed:`, not binding) a competing rendering (another Hindi word with Dice >= 0.6 for the same English
  word), unstable evidence (fails without its best day and best source), a Hindi word already bound to another English
  word. Clean pairs are PROPOSED too for now (`AUTO_LEARN = False`, Oct 16 2026: the owner sees what the aligned rule
  learns first; True binds clean pairs automatically, at most 5 a run, into `terms:`). `fidelity.terms_in` uses hand-written terms
  first, then learned ones (`all_terms`; a hand-written English word always wins); learned terms do NOT change
  `hindi.cache_version` (no re-translation bill). The owner approves a proposal by moving its line to `terms:`, refuses
  with `rejected:` (also drops a learned term). The file is rewritten each run from memory plus the owner's edits;
  counts only, no article text. Logged "glossary candidates: {funnel}". Tests: `tests/test_learn_glossary.py`.
- **The learners replayed on stored data (Oct 16 2026, session 12; `tools/audit.learners_report`, dry run over the
  14 days of retained text, memory empty, no model).** Titles: 53 sightings, 28 words; most stopped by the one-person
  rule ("Sabha" before Rahul Gandhi: "Leader of Opposition in the Lok Sabha Rahul Gandhi"), "Justices" and "Answers"
  still short of days / an anchor; nothing proposed. Synonyms: 16 sightings in 13,022 merged statements (13 pairs),
  most blocked by evidence against ("remark / statement", "raid / search" stand in one statement); the signal is rare,
  not the bar. Glossary (story-level, before the fix): 309 pairs, real ones ("arrested = गिरफ्तार", "complaint =
  शिकायत", "flight = विमान", "hearing = सुनवाई") beside junk from shared stories; fixed by sentence alignment and
  proposals only. Changes from it: a word tagged loaded counts only after 3+ readings tagged it (`learning.loaded_set`:
  one reading tagged "relief" and "detained"); a title's one-person rule needs 5+ sightings, and a block from shares of
  the evidence is re-judged as evidence grows (only the never list and a loaded word block a title for good).
- **Context for everything learned (Oct 16 2026, context plan session 1; `context.py`).** The owner: "bank" is a
  financial bank, a river bank, a road's bank; counting repetitions adds senses together. A sighting carries its
  CONTEXT: the story's section (first secondary, else primary, `section_of`; "" before publication, when sections do
  not exist yet) and the content WORDS of its sentence (stemmed / folded; stop words, numbers, names, the word itself
  out). Sightings group into SENSES (section + signature: words seen in 2+ of its sightings, all words while it has
  under 3). JOIN is generous: a sighting joins the senses of its section sharing any word, and a sighting sharing
  words with two senses of a section merges them; with an unknown section it needs 3 signature words. USE is strict
  (`best`): the sense of the sentence's section with the most signature words, at least 2 (3 with an unknown
  section), strictly more than any other; no match = nothing stored is used (a new context never borrows another
  context's entry). Two renderings in different contexts are two senses, not rivals. `story_sections` reads published
  pages' sections. The learners and translation move onto senses in the next sessions. Tests: `tests/test_context.py`.
- **The glossary by context (Oct 16 2026, context plan session 2; `learn_glossary.py`, `fidelity.terms_in`,
  `hindi.terms_for`).** LEARNING: partners are found WITHIN EACH SECTION (stories grouped by `context.story_sections`;
  "" before publication), so "bank" can pair with बैंक in markets and with किनारा in weather; inside a section each
  sighting joins a SENSE by its English sentence's words (`context.assign`; senses per English word in
  `learn_candidates` kind "glossary_ctx"). One candidate per word, sense and rendering (kind "glossary3", key
  "bank = बैंक @bank#1"; senses a sighting bridges are merged with their candidates; earlier kinds "glossary",
  "glossary2" deleted). RIVALS only within one sense (another rendering with at least half the stories); "already
  bound" only within one section. AUTOMATIC learning ON (owner, Oct 16 2026). The file's terms carry `section` and
  `context` (up to 12 signature words; no sentences). USE: `fidelity.terms_in(english, section)` binds a learned term
  only where the sentence's context matches one of its senses (`learned_sense`, context.best: the section and 2+
  context words, strictly best; a hand-written line with no section or context applies everywhere; hand-written
  glossary.yaml terms always win and apply everywhere). The story's section reaches translation through
  `hindi.SECTION` (a context variable set in `compose._translate`; one per thread). TEMPORARY SENSES (owner: a new
  context is translated by the model and kept as temporary until real evidence comes): after a batch, for a learned
  word no sense matched, if exactly one of its known renderings stands in our Hindi, that choice is saved with the
  section and sentence words (`learn_candidates` kind "glossary_temp", expires after 30 days unused) and binds later
  sentences of a matching context (`hindi.terms_for`, after learned senses, which always come first). A temporary
  sense is never evidence for learning. Tests: `tests/test_learn_glossary.py` (the bank example end to end).
- **Synonyms by context (Oct 16 2026, context plan session 3; `learn_synonyms.py`, `relate.learned_map`).** Each
  sighting (two merged lines differing in one word) carries the story's section (`context.story_sections`) and the
  other words of both lines, and is placed in a SENSE of its pair (`learning.place_sighting`, senses in
  `learn_candidates` kind "synonym_ctx"; shared helpers `merge_into`, `sense_context`). One candidate per pair and
  sense (kind "synonym2", key "allegat charg @allegat charg#1"; the old kind "synonym" is deleted). Evidence AGAINST
  a pair (both words in one statement, the swap between contradicting statements) applies to all its senses. The bar,
  the advocate and the model's look are as before, per sense; only HAND-WRITTEN groups pre-empt a pair (learned pairs
  may share words across senses). The job REWRITES synonyms_learned.yaml from memory: the owner's `rejected:` and his
  lines without `context` (they apply everywhere, `relate.load_learned_groups`), then each learned sense with `section`
  and `context` (12 words). USE: `relate.relate` first decides without learned senses; if not same/covers, a learned
  pair with one word in each line whose context fits (`learned_map`, context.best over the lines' other roots; the
  section is unknown in relate, so 3+ context words) maps one word onto the other and relates again (kept unless
  "different"). Tests: `tests/test_learn_synonyms.py` ("charge" = "allegation" in courts, apart from fees).
- **Titles by context (Oct 16 2026, context plan session 4; `learn.py`, `titles.role_of`).** Each sighting (a word
  mid-sentence before a quoted person's full name) carries the story's section and the words of its sentence (the
  title and the name's words left out; `learn._sentence_at`) and joins a SENSE of its word (`learning.place_sighting`,
  senses in kind "title_ctx"). One candidate per word and sense (kind "title2", key "Skipper @Skipper#1"; old kind
  "title" deleted). Bar, people, anchors, shares and the model's look are per sense; lower-case use is the word's (kept
  on the sense store, copied to each sense). The owner's refusal, `never_titles` and loaded tags hold for every sense.
  Approval is per (word, section) (`approved()`; a line without `context` approves the word everywhere). Proposals
  carry `section` and `context`; ids `learned_<word>_<section>`. `titles._learned` lets several learned lines WITH
  context share a form; `role_of(phrase, context)` uses such a line only when the context text fits it
  (`_sense_for`: context.best with unknown section, 3+ of its words, strictly best), else the hand-written or plain
  entry, else None. The word sets (title_words, person_title_words, role_nouns) stay context-free: a learned title
  word before a name is evidence of a person in any sense; what depends on context is WHICH role and its ref.
  `learning.merge_into` now also adds up counters and count tables of merged senses. NOTE for the owner: the
  hand-written titles.yaml maps "Captain" only to the Army role `general` (a cricket captain too).
  Tests: `tests/test_learn_titles.py` (Skipper in sports and at sea).
- **Negation written into a word (Oct 16 2026, context plan session 5; `polarity.py`, `config/negation.yaml`).**
  "Roads were unaffected" = "सड़कें प्रभावित नहीं हुईं": the checks used to call that a lost/added negation, and
  "affected" read from "unaffected" passed. STRONG forms (the file's `strong` lists, word -> base; plus non-X and
  गैर-X by rule, minus kinds such as NGO = गैर सरकारी in `not_negation`) count as the `negation` qualifier in
  `fidelity.occurrences`, exactly like "not"/"नहीं". WEAK forms (any other English un- word by rule, minus
  `not_negation.en`: unhurt, unprecedented) never count alone, because their usual Hindi carries no negation
  (अभूतपूर्व); in `fidelity._weak_negation` a weak form ANSWERS a negation on the other side, and within one
  language the negation is LOST when the target uses the base word bare with no negation ("unhurt" read as "hurt")
  — added the other way. Statement matching (`relate.Profile`) reads strong forms as "not <base>"
  (`polarity.as_particles`): "unaffected" = "not affected", and differs from "affected". A word belongs in `strong`
  only when its usual rendering in the other language is itself negated. WITHIN ONE LANGUAGE (an English reading of an
  English report) no form counts as a "not": every form is compared through its base only (the audit after session 5
  raised English lost:negation 30 -> 44 with adjectives about something else: "an unidentified projectile",
  "unchanged from April"). Strong forms count as negation only across languages. Tests: `tests/test_polarity.py`.
- **"Captain" by context in titles.yaml (Oct 16 2026, owner).** It was only an Army rank (`general`), so a cricket
  captain read as one. Now `team_captain` (requires_any: cricket/football/hockey/match/innings/IPL/ODI/T20/...;
  ref "the captain") and `pilot_captain` (pilot/flight/aircraft/airline/DGCA/...; ref "the pilot") come after it;
  role_of returns a conditional role when its words appear, else the Army fallback. "Group Captain" stays `general`.
  "Skipper" is left to the learner (it has senses: a cricket skipper, a trawler's skipper).
- **Every statement checked (Oct 16 2026, context plan session 6; `extract.py` rule 10, `fidelity.quoted_window`,
  `find_source`, `readcheck.py`, `tools/audit.py`).** Anchors (numbers, dates, names, entities) found the source
  sentence for about one Hindi statement in four. The reading model now writes `quote` for each item: the first six
  words of the article sentence it read it from, copied in the article's language and script. Code verifies the copy:
  `quoted_window` folds both, ignores punctuation, and needs the quote's words (up to 8, at least 4, shortened from
  the end for a slip) to stand in order exactly ONCE in the report; it returns that sentence (and the next while the
  quote runs on). A translated or paraphrased quote finds nothing and anchors are tried (`find_source` -> "quote" /
  "anchors" / "none"). A sentence found by its quote is the statement's source: when anchors cannot place the
  statement in one of its clauses (`_in_scope`, Hindi), the whole sentence is in scope (`blind_whole`), so "did not
  name any party" read from "...सीधे नाम नहीं लेंगे" is flagged lost:directly with no registry. The quote is stored
  in `claims.rel["quote"]` (newsroom only, never published); readcheck counts by_quote / by_anchors / unsourced per run
  (the run log's "readcheck:" line) and the audit's reading report gives `found_by` per language. Readings stored
  before this have no quote, so coverage shows as new articles are read. Tests: test_fidelity, test_readcheck.
- **Parallel statements joined (Oct 16 2026, context plan session 7; `sentences.parallel_groups`, `keep_together`,
  `link_line`, `narrative._with_parts`).** Owner: "If Modi has said it, they should be joined" (five "Modi will
  inaugurate ..." sentences in a row). Within ONE planned paragraph, statements with the same actor (frame.who: shared
  name words, title words ignored, else the same words), the same action (`frames.action_key`), speaker, negation and
  time, each about a different thing (frame.what), are a group (2 to MAX_PARALLEL = 6). Not grouped: speech actions
  (say, allege, deny, ... : one speaker's points are the same-speaker LINK), disputed or false statements, updates,
  partners (contradiction, response). The plan puts a group's members side by side (at the first one's place; the
  lead stays first); each later member's LINK says PARALLEL: ONE sentence, actor and verb once, the things listed,
  in parts one per statement when statuses differ. COLOUR: each part keeps its statement's colour; `_with_parts`
  accepts up to MAX_PARALLEL parts for a sentence whose ids are one group (else MAX_PARTS = 3); every part is still
  checked on its own. Hindi pages keep one colour per sentence (the weakest), as for all parts. The marks are copies
  on the run's `by_id` (never written to the payload); the fill pass reads them from `by_id`. `sentences.stats` counts
  `parallel` groups and `parallel_apart` (kept in separate sentences) in the page's flow stats. WRITER_VERSION not
  bumped: pages are not all rewritten; new and rewritten pages get it. Tests: `tests/test_parallel.py`.
- **Long reports read in pieces; exact words kept (Oct 16 2026, owner; step 1 of the express plan; `extract.pieces`,
  `read_report`, `_merge_pieces`, `check_words`, `compose._exact_words`, `narrative._validate` quotes).** The express
  review (`tools/express_review.py`, workflow `audit` with tool `express_review`, private diagnostics) showed a report
  gave 7-9 statements whatever its length (a page ~1/6 of its source), long reports were cut at `max_article_chars`
  (17 of 35 live normal stories had one), and quotes were almost never kept. Both routes now: a report past the cap is
  read in pieces of up to PIECE_CHARS (5000) split at paragraph breaks, each starting with the last paragraph of the
  one before and told the article's opening (MAX_PIECES = 4 reading calls at most); ids prefixed "p2-", an item read
  twice in the overlap (same text or relate "same") kept once; a later piece the model cannot read leaves the
  pieces read. Rule 7: every fact sentence gets an item. Rule 11: `words` = a named speaker's EXACT words as an
  English report prints them in quotation marks (each quote its own "attributes" item); `check_words` keeps them only
  when they stand word for word in the report (3+ words; Hindi reports: never, a translation is not their words);
  stored in `claims.rel["words"]`; the payload item's `words` = the most printed version. The writer sees
  `EXACT WORDS: "..."` and may quote them (prompt "QUOTES"); `_validate` refuses words in double quotation marks
  (3+ words) that do not stand in a cited statement's words or text ("quote not in statements"), and a loaded word
  inside a quote is the speaker's, not refused. Tests: `tests/test_reading_long.py`.
- **The express desk (Oct 16 2026, owner; step 2 of the express plan; `coverage.py`, `expressdesk.py`,
  `extract.second_pass`, `narrative` layouts and copy check).** COVERAGE: an express story's report is read for
  coverage: `coverage.fact_sentences` (the report's sentences minus clutter such as "Also read" / "Download the app",
  captions, questions, fragments under 6 words) and `coverage.report` (which of them a statement came from: its
  `quote`, else its anchors). A first reading under TARGET (0.7) gets ONE more reading call on the sentences left
  (`second_pass`, merged like pieces). The article's `extraction["coverage"]` keeps {first, final, sentences, passed
  (final >= MINIMUM 0.6)}; the run logs "express coverage:". Under the minimum the story is still published. LAYOUTS
  (`expressdesk.kind_of` by code: sport with 2+ result-and-score lines = match; companies/tech with 3+ money figures =
  results; one person named in 60%+ of statements = profile; else general): match = background (build-up), happened,
  performers, say, numbers, next; profile = who, journey, words (their own words), next; results = numbers, drivers,
  say, market, next; general = happened, words, say, numbers, background, explained, next. `expressdesk.sections`
  moves narrative.assign_sections' choices into the layout. The writer gets `expressdesk.structure(kind)` instead of
  NORMAL_STRUCTURE and the layout's order; narrative keeps the layout's keys per thread (`_keys()`, `_fill_groups()`;
  plan.build follows them; plan.RULES has the new keys; "words" is planned like "say"); target length: one sentence per
  statement at least. The payload's narrative has `layout`. The site, audio and feed show a page with a key outside
  the normal sections in the order written; new headings in both languages (site/index.html); "words" paragraphs get
  the speaker label like "say". COPY CHECK: a sentence sharing COPY_RUN (10) words in a row with the report outside
  quotation marks is sent in ONE writer call (REPHRASE_PROMPT, at most 12) to be said in our words; kept only if it
  passes every check and no longer copies (`flow.copied` / `flow.rephrased`). PARAGRAPHS: in an express layout
  plan.build fills each paragraph up to MAX_STATEMENTS (`_pack(..., topical=True)`), since a layout section is one
  subject (the first live express pages had one sentence per paragraph). Tests: `tests/test_express_desk.py`.
- **Facts shared along a thread; updates since published (Oct 16 2026, owner; step 3; `threads.save_links`,
  `pooled_origins`, `verify.base_verdicts`, `editions.attach_updates`, site `updatesHtml`).** The follow-up check
  (`editions._classify`) now numbers the parent's statements (E1, E2 ...) and returns, per later statement, `same_as`
  (the earlier statement saying the same fact) and `updates` (the earlier one it replaces with newer information).
  `threads.save_links` stores them in `canonical.rel`: `twins` both ways, `superseded_by` on the earlier, `updates` on
  the later (re-judged: the old links of those later statements are replaced). `base_verdicts` judges the rule on a
  statement's origins POOLED with its twins' (`pooled_origins`: origin keys as one set, outlets by `outlet_keys`, now
  stored by origins.compute_origins as `names.source_key`s, else the largest count; a disputed/false twin makes it
  contested); its own `canonical.origins` stays its own. So one fact has one colour on every page, and a published
  page's line matures as later reports come in (`mature` runs base_verdicts on frozen pages every run).
  `attach_updates` (every run, after `mature`): the page's `updates` = the later statements replacing its lines, each
  with its own colour class, translated for the Hindi page (page tier, cached); the replaced line is `struck` (site:
  line-through, no colour, no wash) once the later one has at least min(3, old line's) outlets; a sentence is struck
  only when ALL its ids are (a part: its own ids). Site: "Updates since published" after the essay, a link to the
  follow-up once it is a child of the page. THE BUG the owner saw (Punjab, 23690): `tools/story_check.py` (workflow
  audit, tool story_check, private diagnostics) showed 42 articles but only 3 READ when it was published (the
  "broad" settle fired on 17 outlets the moment the third was read), so every line was one outlet. Fixed by the
  reading rule in step 4. Tests: `tests/test_threads_shared.py`.
- **Express needs two OUTLETS (Oct 16 2026, owner: a sport story read from two outlets was far better).**
  `express.min_outlets()` (config `min_outlets: 2`): an express candidate needs 2+ outlets with a readable page
  (`express.outlet_key`: the outlet name; one wire copy carried by two outlets counts once; two papers of one owner
  count as two). `select_for_extraction` reads an express story one article per OUTLET (not per owner group);
  `assess` requires every readable outlet read ("one_outlet", "second_outlet_unread" in the funnel). Writer note and
  layout prompt say "one or two outlets". Tests: `tests/test_express_story_db.py`.
- **An express mark is checked again before writing (Oct 17 2026, owner: story 23995, "Vidyut Jammwal plays Dhalsim", went
  out with Aaj Tak "not read").** Cause: the story qualified as express on Oct 13 on one outlet (The Hindu's lane-feed article,
  before the two-outlet rule) and kept `qualifies` = True; its lane article went stale, so `express.candidates` (fresh = a
  LANE-FEED article in 36 h) never took it into `focus` again and `assess` never ran; on Oct 16 Aaj Tak's HOME-feed report
  joined, unread, which made `last_new_source` fresh, and the express settle (met_at + wait, no reading check) sent it to the
  desk on the old mark. Fixed three ways: (1) `editions.settle_reason` asks `express.still_holds` (= `assess` now, code only,
  funnel not counted) before an express story is ready: a readable outlet unread, a third outlet or a dispute = not ready;
  (2) every run `express.revoke_stale` clears an express mark that no longer holds (qualifies False, dirty True; run stat
  `express_revoked`, funnel `story_revoked`), so no verdict or writing call is spent on it; (3) `express.candidates`: a story
  with a lane-feed member in the last `LANE_MEMBER_DAYS` (7) is current when ANY member is fresh, so a late second outlet from
  a main feed gets read. Story 23995 itself is published and closed (left as is). Tests: `tests/test_express_story_db.py`.
- **No settling wait (Oct 16 2026, owner; step 4).** `editions.settle_decision(now, last, met, unread)`: a story is
  written as soon as the publishing rule is met (3 independent sources read) AND `unread_sources` is 0 (no readable
  independent source of the story left unread within `max_extract_per_story`) -> "read"; or `read_wait_hours` (2)
  after the rule was met -> "cap" (reading did not catch up); never when stale. The quiet hours, the 8-hour cap and
  "broad" are gone (settings kept, unused); run stat `settled_read` replaces `settled_broad`. Express:
  `wait_for_second_hours: 0` (two outlets are read before it qualifies). Tests: test_pipeline
  `test_a_story_is_written_once_the_rule_is_met_and_its_reports_are_read`, `test_article_is_written_once_its_reports_are_read`.
- **"Latest in this story" was never shown (owner, Oct 24 2026: older articles had no link).** An article is written before anything
  develops it, so `payload.children` is written as `[]`, and nothing ever filled it (`threads.relatives` had no caller; 0 of 65 live
  files had children while 15 articles were follow-ups). Now `editions.attach_children(store, only=None)` sets every parent's
  `children` from `story_links` (live follow-ups only, oldest first so the newest is last; the Hindi page gets Hindi headlines;
  text never changes; written only when the list changed, so the feed stamp moves only then). Automatic: `compose` calls it for the
  parents right after a follow-up is inserted (the link shows at once) and `run.py` calls it for every page each run (stat
  `children_attached`), so a missed or failed attach is repaired the next hour and existing articles get their link at the next run.
  Tests: `tests/test_threads_shared.py`. Colours were already live (`editions.mature`); few lines ever turn developing because a
  closed article takes in no new reports, so only lines that met the 3-outlet / 2-origin rule at writing time can ripen.
- **"Latest in this story" as a thread rail (owner, Oct 25 2026, design "2e").** Each `children` entry now carries `at` (the follow-up's
  publish time, ISO, for "3 h ago"). The site shows the newest child in `#latest` (`fillLatest`, called by the `fillSheet` wrapper), between
  the colour key and the headline card: a node and a 2px rail that runs down to the card, kicker + age, the headline (2 lines), "Read the
  latest →" (`latestGo`). Not inside `#rise` any more; it fades in with the article (`#sheet:not(.open) .latestin`), never animated by size.
  Older pages get `at` at the next run (the list differs, so `attach_children` rewrites them once). `sw.js` np-main-68.
- **Latest in this story; colour notifications (Oct 16 2026, owner; step 4).** Site: an article with later
  developments opens with a "Latest in this story" link to its newest child (`latestin`). Notifications: follows of
  kind "colour" (key established / developing / disputed / false; Supabase check constraint widened, migration
  20261016000100_follow_colour.sql) chosen in the Following sheet ("When lines change colour"); `notify.queue_colours`
  (every desk run, after queue_articles) compares each live article's line classes (`line_classes`, parts on their
  own, struck lines skipped) with the last look (notify_state "colours"; the first sight only records) and queues ONE
  notification per reader per article per IST clock hour (kind "colour", ref "story@hour"): "2 lines now established
  · 1 line now sources now disagree". For every live article, not only followed ones (owner). Tests:
  `tests/test_notify_colours.py`.
- **One result however it is worded (Oct 16 2026, owner; `relate.result_of`, `_result_relation`).** An express page
  wrote one match twice ("Suhas LY defeated Joytu Dhar ..." / "Suhas LY overcame Joytu Dhar 21-8, 21-11 ..."; and
  "Joshi and Raghupati lost to Sadiyah and Setiawan" / "Sadiyah and Setiawan defeated Joshi and Raghupati 21-15,
  21-4"). `result_of` reads (winner names, loser names) from a line with a win verb (defeated, beat, overcame, edged,
  thrashed ...) or a loss verb (lost to, went down to, was beaten by ...): the capitalised run right before / after
  the verb (class codes such as SL4 and leading "On Saturday," left out). Two lines with the same winner and loser are
  one result: same score numbers (class codes removed) = "same", one score inside the other = the scored line covers;
  opposite sides = "different"; two contests told apart by stage, kind of event or sport (`_EVENT_DIMS`: both name
  one and share none) = left to the normal rules. Runs inside `relate.relate` when the word rules found no relation,
  so matching, consolidation and `narrative._drop_repeats` all see it. Tests: `tests/test_relate_forms.py`.
- **Open (Oct 16 2026):** `tests/test_express_db.py::test_nothing_is_embedded_while_the_pacing_curve_has_given_the_slice_out`
  fails at some hours of the day (failed at ~05:30 UTC with and without the session 9 changes, passed at 04:xx).
- **Audits (Oct 16 2026; `audit.py`, `tools/audit.py`, workflow `audit`, read-only, no model).** Over every live article:
  missed merges (statement pairs with 60%+ shared root words left apart, by the language mix of the story's sources:
  en / hi / mixed, and what code and the twice-asked question said of them), English left in Hindi pages (by field, top
  words), repeated sentence openings, mixed date / money / per-cent forms in one article. Summary in `diagnostics` kind
  'audit'. **Tool diagnostics go to Supabase:** replay, modelcmp, probe and audit wrote their reports into the job's
  newsroom copy since Oct 10 (thrown away at the end); they now use `store.readers.engine`.
- **Flaky tests (seen Oct 8 2026, before the split work too):** `test_a_later_development_links_to_its_story_and_gets_background`
  and `test_published_article_is_closed_and_only_its_colours_mature` fail about 1 run in 3-8; they pass alone.
  Find the nondeterminism (set order, wall clock) before trusting a red run.
- **Check next session (owner, Oct 7 2026):** do resumed drafts' extra fill rounds use up Flash writer quota early (desk `diagnostics` kind 'desk', `tier_calls`)? If Flash runs out by afternoon, drop the third round for resumed drafts first.
- Green rule may be too strict (own-voice reporting rarely counts as an origin); revisit with data.
- Thread timeline page (later). Weak fallback headlines when the model fails twice.
- Perspective clusters flipped because they were noise (Oct 5 2026: 32 sources, 21% of pairs
  observed, 1,020 of 1,164 pairs seen once, agreement centred on 0, silhouette 0.04-0.07, resample
  ARI 0.02-0.68). Now shown only if stable under resampling (`global_min_stability`), and live pages
  are relabelled when clusters change.
- **Perspective units and evidence (owner, Oct 5 2026):** clustered over OUTLETS; each article is
  still scored on its own and departs from its outlet's perspective only on strong evidence
  (margin 0.5, 3+ items; shown with †); an author with 3 of their last 5 assessed articles departing
  becomes their own unit (`refresh_units`); outlets whose articles depart ≥30% are flagged in health.
  Evidence, strongest first: stance on contested facts (1), whose named voices are carried (0.5),
  loaded words for the same fact (0.5), omission (0.15). Never anything about the outlet itself.
  At outlet level on the old omission-heavy signal: silhouette 0.07, resample ARI ~0.35 (still noise,
  gated off).
- **Perspectives must pass the daily positions test (`positions.py`, owner Oct 5 2026).** Like with
  like only (same story, same fact); evidence: OMISSION as the main signal (each side leaves out
  what is inconvenient to it; a fact counts as left out only if 2+ independent sources report it and
  `textmatch` finds its names/numbers absent from the outlet's text, across Roman/Devanagari),
  stance, framing (Hindi loaded words mapped to English concepts, `concepts.py`), voices. Model: 1-D
  ideal points; signal only if stable under resampling (r>=0.7), 15%+ of outlet pairs separated,
  and clearly better than outlet names shuffled per story. No signal, no perspectives at all.
  Offline on Oct 5 data: no method beat the shuffled baseline (too few multi-outlet stories).
  Clusters on voice kinds or raw words were rejected: they found genre and language, not lean.
- **Read in depth:** a story is read once 3+ independent sources have a readable page
  (`min_sources_to_read`); stories already being read are finished first.
- Writer failures on big stories: the reason is now split ("empty sentence" / "no valid ids" / "too
  long", plus reply-level `failure`); read `stories.analysis.writer_failures` before shortening input.
- Fallback sentences append `when_text` that can be relative to another event ("on Thursday, a day
  before his arrest" on the arrest itself); prefer the absolute date in fallbacks.

## Fixed at the root (Oct 2026), keep the guards
- Story 14231 (Oct 8 2026): one "What they say" paragraph of 18 lines, each "..., according to Modi".
  Code finds a paragraph naming one speaker in 3+ sentences or running 7+ sentences (`narrative._cohere`)
  and one writer call rewrites it (speaker named once, then "he said" only where the statements make the
  gender clear, else the surname; grouped into 2-3 paragraphs by subject); kept only if it passes every
  check and carries every statement, at most 2 per article. Code never writes a pronoun itself (it cannot
  know anyone's gender). Also: days and months are not names, and the numbers of a date are not figures
  (`relate.Profile`: "on Thursday, October 8, 2026" kept one call told twice apart); two lines with
  different years or dates are never one fact.
- Story 11867 (Oct 8 2026): (1) dispute marks made before the dispute gate were published, because the
  story was never reviewed again: the desk now runs `consolidate_story` before writing (a no-op when the
  review is current), so an article is written only from analysis under the current rules; (2) the
  validator rejects a sentence naming the same multi-word name twice ("repeats a name"; disputes exempt)
  and the fill pass rewrites it; the writer is told to use "the river", "he", "it" the second time.
- Story 12687 (Oct 7 2026): (1) `style.py` shortened "Commission for Air Quality Management" to
  "Commission for Management" ("Air" read as a title): only PERSON_TITLES count as evidence of a person,
  and institutional words (Management, Commission, Quality...) are never a person's name; (2) a page's text
  about its own publisher ("Hindustan was established in 1936 ...") is dropped by code
  (`compose.drop_outlet_self_talk`) and extraction is told to ignore it; (3) every article opens with a
  news lead: a missing "news" section triggers the news fill, and failing that the first "What happened"
  paragraph becomes the lead; (4) "By the numbers" takes figures only, never years or dates
  (`narrative._is_figure`); (5) a context line that shared no word with the story was dropped by code;
  replaced Oct 8 2026 by the model check (see "Context: better a line that makes a reader wonder"): words
  dropped real context. A page's text about its own publisher is still dropped (`drop_outlet_self_talk`).
- **Context: better a line that makes a reader wonder than a missing one (owner, Oct 8 2026; `belong.py`).**
  Story 12099: a Kerala vigilance probe under Related events in the cheetah story (a video page's list of
  other videos); on the 60 latest articles many context lines were other news from the page (a cricket
  comeback in a story of students' deaths). Owner's rule, for background, related and explanation alike:
  "It's better to have something unrelated in the story and think, why is this here, than not to have
  something important." So a line is dropped ONLY when the model says "other news" twice (one plain
  question, connected / other news, the story's news and own statements in front of it, worked examples;
  a line is asked again, lines reversed, only after one "other news"); one "connected", no answer (quota)
  or a model that never answers keeps it; the story never waits for this. Answers kept per line text in
  `stories.analysis.context_checks`. Reactions and "what next" are not asked. NO code rule drops a context
  line by its words (the no-shared-word rule dropped "Indian Air Force helicopters dropped rations in Saran"
  in a story on Saran's flood victims; a word rule dropped "the project is expected to generate employment"
  in the project's own story). Tried and rejected on 16 real stories the same night: per-role bars
  ("connected" twice for related and explanation, a named term for explanations): they lost the Prakash
  Singh rules in a DGP story when the model wavered once, and "Section 22" in a story on voter deletion.
  Reading is told to ignore other stories a page lists (`extract.py`). `replay --mode context` runs only
  this check on stored stories (unpaced: run it after the 12:30 IST reset, it spends the writer's quota).
- Story 16000 (Oct 9 2026): one hearing written three times although covered lines existed for exactly that.
  `perspectives.analyze_story` rewrote `stories.analysis` keeping a FIXED LIST of other fields: "consolidated" was
  on it, the review's results were not, so covered lines, updates, doubtful disputes and the cached same /
  conflict / topic answers were wiped every run, and the desk's own review saw the story as done. Doubtful
  disputes block green, so this could also show a statement as established. Now every stage's work survives
  (`{**old_analysis, ...own fields}`); `CONSOLIDATE_VERSION` 10 reviews every story again. Any stage writing
  `stories.analysis` must read the whole record and change only its own fields. The split moved to the
  analysis tier ("light"): the reading tier refused 14 of 15 calls in a night run and nothing was split.
- One spelling per name in an article by code (`spelling.py`, Oct 7 2026: Machhar / Machar / Matchar /
  Machchhar on one page): capitalised words with the same key (tch/chh = ch, ee = i, oo = u, doubled letters
  single) take the spelling most reports use; applied to statements before writing and to the article and
  headline after. The consolidation model's `names` alone missed these.
- The same news is never published twice (Oct 7 2026: one Supreme Court order published as 11593 and
  11663 a minute apart): the thread check also asks for earlier articles reporting the SAME news and
  links them like a parent, so the story must pass `follow_up_ok`; it re-checks whenever an article was
  published since (`analysis.thread_checked_at`), and an article published first can be the parent
  whichever story was opened first.
- Name consolidation maps only spelling variants (`consolidate.is_spelling_variant`); aliases were
  rewriting "X, also known as Y" into "Y, also known as Y". Old bad mappings are undone on the next run.
- `when_text` is extracted in English; `narrative.english_when` converts any stored Devanagari.
- Writer validator rejects Hindi in English text, and reported speech ("A said that B claimed X")
  turned into a fact or pinned on A.
- `compose.tidy` removes "X (X)" duplicates.
- Story 13058 (Oct 9 2026): "Nana Patekar was an extraordinary artist ..." (Modi's words, read as his by reading)
  opened the article as a plain fact: a statement's speaker came only from the review model's list, which missed
  81 of the 627 lines on the 40 latest articles that every report gives to someone. Now, when every report of a
  line gives it to the same speaker (stance "attributes", one `attributed_to`), that is its speaker
  (`compose._reading_speaker`); an outlet, "media" or "reports" never is.
- Story 16197 (Oct 9 2026): the Hindi report names Chief Justice सूर्यकांत; reading wrote "Chief Justice Sanjiv
  Khanna (referred to as Chief Justice Suryakant in the text)", a name from the model's own out-of-date memory, and it
  was published. Reading now drops (never patches) a statement naming a titled person the report does not name in
  any spelling or script (`textmatch.absent_people`: names written in one rough Roman form with vowels, both scripts;
  same consonants or close spelling = present; a name split differently counts), or a note about the text itself
  (`extract.ground`, `extract.META`); the prompt says names, posts and numbers come only from the article. On 183
  real statements naming a titled person (Hindi and English) it flagged only that line.
- Story 15429 (Oct 8 2026): the page models were overloaded mid-translation and the Hindi page went live
  half in English. The desk now finishes half-translated Hindi pages after writing
  (`compose.finish_translations`, selected in SQL by `payload_hi.translation_complete = false`, up to 3 per
  run; cached strings cost nothing). Only the translation is completed; the English article stays closed.
- Run stats: `rated`, `queue`, `settled`, `colours_matured`, `live_pages`; the desk's own stats are in
  `diagnostics` (kind 'desk': ready, tried, published, tier_calls). Health flags a writer with 0
  successes in the desk's last 2 runs and two clock hours without an article while stories are ready
  (`run.writer_silent`). `published.updated_at` is the publication time.
- The news pick puts the newest day first and the past last (`news.pick_news`); sorted by support, old
  background outranked the new development and got tied to it with "after".
- Notification came, article not on the home page until the app was opened a few times (owner, Oct 11 2026). The
  feed is files on raw.githubusercontent.com, which keeps serving the old ones for minutes after a force-push; the
  minute in the address did not help when the CDN origin itself lagged, and a story file asked for too early was
  answered "missing" from cache. Now: `publish_feed.sh` pushes with 3 tries and waits (up to 240 s) until the CDN
  serves THIS export's `generated_at` before the notification step; the push carries the story id and `sw.js` tells
  open pages (`np: "fresh"`), which read the home page again, and again if that story is still missing; the site asks
  the database for anything newer than the feed's newest card (`newerThanFeed`, ~0 bytes when nothing, 4 s limit,
  also every 3 minutes while looked at) so the home page is as fresh as the notification whatever the CDN does;
  returning to the page refreshes after 30 s (was 2 min); story files are asked for with `?v=<stamp>` and
  `no-cache`; times are compared as UTC (`utcMs`), not as the phone's local time; the service worker keeps feed files
  under one address (it kept one new entry a minute). Guard: do not send notifications before the feed step.
- Unused hourly allowances carry to later hours (owner, Oct 11 2026, `nishpaksh/carry.py`, `SETTINGS.carry_over`).
  Gemini requests already did (`router.pace_cap` is cumulative). Now also our own: the writer's seats
  (`desk_per_hour`, `desk_beat_seat`: the articles published since midnight Pacific are subtracted from every hour's
  seats so far; one run takes at most `desk_carry_burst_hours` = 3 hours' worth, and gets 2 more tries per extra seat),
  stories searched per run, Tavily pages and searches per run (spending booked in `quota_usage` as `carry:<name>`,
  at most `carry_burst_hours` = 6 hours' worth in one run). The bank is emptied at midnight Pacific, Google's reset
  (`router.quota_day`). Hard limits (per minute, per day, Tavily's credits) are unchanged: carrying only moves our own
  pacing. `desk_per_hour` is therefore an average now, not a ceiling for one clock hour; set `carry_over=False` for
  the old rule. `prep_queue` is a width (how many stories are prepared), not an hourly quota, and is unchanged.

## Talk to the article: live voice conversation (owner, Oct 11 2026; built and designed, NOT yet deployed)
A reader talks to Gemini's **Live API** about ONE article and can interrupt it at any time. **Built first, designed second (owner):
the design is now in `site/index.html` (below); `live/test.html` stays a plain test page.** Name: "Understand by talking" /
"बात करके समझें".
- **Flow:** tap -> microphone permission -> `live-token` Edge Function (login, limits, the article's brief, a ONE-USE Gemini
  token) -> a fixed intro recording plays ("this is a live conversation, interrupt any time" ... pause ... "what would you
  like to know?") while the WebSocket opens -> the microphone opens -> the reader just talks. **No suggestion chips (owner):
  talking is the point.** The browser talks to Gemini directly (no proxy) and never holds a Gemini key.
- **Models:** `gemini-3.8-live` (LIVE_MODEL secret; Live models are capped in TOKENS a minute, 65K, not in requests; the
  dashboard shows no concurrent-session cap, so `CONCURRENT` in the function is a guess to be tuned). `3.8 Live Extended
  Thinking` is for harder questions later; `3.5 Transcribe Live` for voice search; `3.5 Live Translate`: not used yet.
- **Grounding is code's job (`supabase/functions/live-token/brief.ts`, pure, tested):** the model is given only the article's
  own sentences, each as `[p2s0] (STATUS; sources 1, 3) text`, the status = the site colour in words (`STATUS`), the sources
  list, and short rules with the traps as worked examples (never more certain than the status; ONE OUTLET ONLY is not
  confirmed; no outside knowledge; "the article does not say"; a suicide story adds the Tele-MANAS 14416 rules). A sentence in
  two colours is one line per colour (`p2s0.1`). Ids are the (p, s) numbers of `audio.py`'s timing files. The model cannot
  make a sentence look more certain: it **calls `highlight(id)`, and the browser lights the sentence up in its OWN colour from
  the page data**; an id that is not in the brief is ignored (`LiveProtocol.validId`). What the model SAYS about status is
  still the model's; that is why the brief repeats the status of every sentence and the rules include the traps.
- **Limits are in the database, not the browser (`migrations/20261011000100_live_talk.sql`):** `live_talk_begin` = 3 a reader
  per IST day (`DAILY`), 4 at the same moment site-wide (`CONCURRENT`), a row's age says whether it can still be running
  (`MAX_SECONDS` 480; the token itself expires then, so Google enforces the cap), `live_talk_cancel` when the token could not
  be made. Only `service_role` can call them. Conversations are spread over the keys by the day's count; a refusing key hands
  over to the next. Rows older than 14 days are deleted by the next call.
- **Token:** `POST v1beta/auth_tokens` `{uses: 1, newSessionExpireTime +60 s, expireTime +60 s + MAX_SECONDS,
  liveConnectConstraints: {model, config: {responseModalities, systemInstruction}}}`; the browser connects to
  `...BidiGenerateContentConstrained?access_token=<name>` and repeats the same instruction in its setup message.
- **Browser (`live/talk.js`, one dependency-free ES module):** `createTalk({tokenUrl, getHeaders, introBase, onState,
  onHighlight, onTranscript, onLevel, onGrant, onEnd, onError})`, `start({storyId, lang})`, `stop`, `skipIntro`, `setMuted`.
  Audio in: 16 kHz PCM from an AudioWorklet (ScriptProcessor fallback); out: 24 kHz chunks queued back to back; on the
  server's `interrupted` all queued playback stops at once. Ends by itself: 45 s of silence, `MAX_SECONDS` (the guide is
  asked to say goodbye 20 s before), the server's `goAway`. Error codes: login, limit, busy, gone, mic, network,
  unavailable, refused (the socket closed before `setupComplete`).
- **Intro recordings:** words in `live/intro.json` (en, hi); `python -m nishpaksh.live_intro --dir live-out` makes
  `intro-en.m4a`, `intro-hi.m4a` with the audio.py TTS models and voice (4 TTS calls). Until they exist the browser reads
  the same words in its own voice. Where they are served from (the `audio` branch, or next to the page) is for the design phase.
- **Tests (no browser, no Gemini):** `node --test "tests/live/*.test.mjs"` (brief, audio conversion, protocol, and the
  controller against a fake AudioContext / WebSocket / microphone; CI runs it) and `tests/test_live_intro.py`.
- **NOT verified (needs the real thing; first run, in this order):** (1) apply the migration (Supabase MCP
  `apply_migration`, as every migration); (2) deploy `live-token` with **verify_jwt off** (like `account`) and set the secrets
  `GEMINI_API_KEY`, `_2`, `_3` on Supabase (they are GitHub secrets today); (3) `cd live && python -m http.server 8000`, open
  `http://localhost:8000/test.html`, log in, "Latest article", "Talk". If Gemini closes the socket straight after setup
  (`refused`, close code and reason in the console), the setup layout is the first suspect: `setupMessage({nested: true})`
  puts `responseModalities` and `speechConfig` under `generationConfig`. Then check: Hindi speech and answers, whether a
  question the article cannot answer gets "the article does not say" (try 10 per language, incl. leading ones: "so the minister
  resigned, right?"), the `SILENT` tool response (the guide must not talk about the highlight), echo on a phone speaker, and
  how many conversations at once the 65K tokens a minute really carry.
- **Privacy, decide before it ships:** the free tier lets Google use API content to improve its products, and this sends a
  reader's VOICE. The button needs a consent line (design phase); readers' audio is never stored by us.
- **Speed (owner, Oct 11 2026: "the talk bot takes too long to answer"):** the guide sees ONLY the article the reader is on and the earlier articles of its story (the page's own `parents`, at most 3, 40 sentences each, put into the instruction at the start by `live-token`). The `read_article` function, its `read` endpoint and the 30-headline list are gone: a call to it cost browser -> function (login check) -> GitHub -> browser -> model while the reader waited, and the rules told the model to use it for any question beyond the page. The function no longer fetches the whole feed either. The login check and the page are fetched together. Reader-quiet time before the guide answers: 700 -> 500 ms (`SILENCE_MS` in index.ts; the browser takes it from the grant, `silence_ms`, so the token and the setup always match). `highlight` can be made non-blocking (`behavior: NON_BLOCKING`, so the guide need not stop for it) by setting the secret `LIVE_NONBLOCKING=1`; NOT verified that the Live model accepts the field, so it is off. The function sends `tools` in the grant and the browser uses them.
- **Big questions went silent (owner, Oct 11 2026: "long UPSC-style questions: it thinks too long and says nothing"):** causes found by reading the code (NOT yet measured on the real model): (1) the rules asked for "as much as it needs, up to a minute" and for a `highlight` before every sentence, so a "get all the points and highlight them" request made the guide plan one long answer and call `highlight` many times first, each call BLOCKING (a round trip before the next word); (2) the model reasons silently before speaking and nothing limited that; (3) the page fell back from "thinking" to "listening" after 20 s and the 45 s idle end did not know the guide was working. Now: the rules say answer a big request in parts (one short sentence at once, 3-4 points, "Shall I go on?"), highlight once per sentence as it is reached and at most five times; `LIVE_THINKING_CONFIG` (secret, JSON such as `{"thinkingBudget":0}`, validated by `voice.thinkingConfig`, sent in the token and repeated in the browser's setup; OFF until set because the field names are not verified for this model); `talk.js` calls `onSlow(true)` after 2.5 s without an answer (the site shows `talkSlowHint`), thinking may last 60 s, and waiting counts as activity. To do next, in this order: set `LIVE_NONBLOCKING=1`, then `LIVE_THINKING_CONFIG`, and time "first word" for the same big question before and after.
- **Follow-up, same evening (owner: simple questions also slow, "Shall I continue" after every answer, the noise gate ignores the reader):** (1) the big-request rule had spread to every answer, so it now applies only to many-things-at-once requests, asks "Shall I go on?" ONCE, gives everything left when the reader says yes, and a new rule says every other question is answered directly with no opening line and no closing question; (2) the browser gate was too strict for a soft voice (`GATE` was 0.02 / 2.5 / 400 ms / 0.03, now 0.012 / 2 / 500 ms / 0.02; a soft voice in a NOISY room is still shut out) and the function can switch it off with the secret `LIVE_NOISE_GATE=0` (audio goes to Gemini as it is; the gate still drives the page cues); (3) `talk.js` reports `onMetric({firstAudioMs, firstToolMs, tools})` after every answer and the site logs it in the browser console as "talk timing": about 1000 ms of it is waiting for the end of the reader's turn (gate hang 500 + Gemini silence 500); a large firstToolMs means blocking highlight calls, a large firstAudioMs with no tool means the model is reasoning (set `LIVE_THINKING_CONFIG`). Not measured on the real model: if simple questions are still slow, delete `LIVE_NONBLOCKING` and compare the timings.
- **The 10+ second silence was a stall, not slow thinking (owner, Oct 11 2026, night: "when I add 'go ahead and tell me now' it answers instantly"):** `LiveProtocol._tools` answered EVERY function call with `scheduling: "SILENT"` (write the result, do NOT generate). That is right only for a NON_BLOCKING function; for an ordinary one the model has stopped to wait for the answer and then never carried on until the reader spoke again, so every answer that began with a `highlight` froze (it also explains the very first complaint, long requests that highlight a lot). Now SILENT is sent only when the grant's tools declare NON_BLOCKING (`LiveProtocol({nonBlocking})`). Safety net (`talk.js` `watchdog`): when the reader's question was heard and the guide was answered about a highlight and stayed quiet for 1.8 s (or nothing at all came back for 7 s and the guide ended no turn), the page sends "Go ahead and answer now." ONCE per question and reports it through `onMetric({nudged})`; a guide that ended a turn silently with no function call had nothing to say (noise) and is left alone. Tests: `tests/live/watchdog.test.mjs` (real time, ~8 s). Recommended: delete the secret `LIVE_NONBLOCKING` (not verified that the Live model supports it; the standard blocking flow is now correct).
- **Instant start (owner, Oct 11 2026, night: "the card loads at once but the speaker starts after a long time"):** the guide saying the intro itself had to wait for login + token + socket + its own speech (several seconds of nothing). Now `talk.js` starts a RECORDING on the tap, before the microphone prompt, the login and the socket: `intro-<Voice>-<lang>.m4a` (one per voice the reader can pick, so it sounds like the guide; words in `live/intro.json`), fetched early by `preload` (the site calls it when `talk.js` loads and when the voice changes) and decoded on the tap. The microphone opens only after the recording and the socket are both done. No recording for that voice, or not started within 4 s of the connection being ready: the guide says the intro itself, as before. Make the files with `python -m nishpaksh.live_intro` (all ten voices, both languages, into `live/`; 2 TTS calls a file; it skips files that exist and stops when the quota is gone, so run it again next day; `--voice Kore` for one), commit `live/intro-*.m4a`; `site.yml` already copies them. Without a terminal: Actions -> `live-intro` -> Run workflow (`.github/workflows/live-intro.yml`, by hand, uses the GEMINI_API_KEY secrets, commits the new files to main and starts `site.yml` itself because a push by the job's own token does not). If Hindi is asked for but the story has only an English page, the recording is still the Hindi one. Tests: `tests/live/clip.test.mjs`, `tests/test_live_intro.py`.
- **Start-up time, measured (owner's network log, Oct 11 2026):** the first `live-token` call took 2.0 s for the browser's permission check (CORS preflight, a cold function) plus 3.6 s for the request, about 5.6 s before the socket could even open; the pings every 15 s each paid a 250 ms preflight too. Now: `Access-Control-Max-Age: 7200` (the preflight is remembered), `{warm: 1}` calls (`talk.warm()`; the site sends one when `talk.js` loads and whenever an article is opened, at most once a minute) so the function is started before the tap, stories fetched in the last 60 s are kept in the function's memory (`getStory`), and the grant carries `timing` (ms since the call began: login, article, earlier, begin, mint) which `talk.js` reports with the socket's time as `onMetric({grantMs, server})` / `({socketReadyMs})`, printed in the console as "talk timing". The recording (above) hides what is left. Not measured after the change.
- **Talk to the DAILY RECAP (owner, Oct 12 2026: "a special talk bot for the recap that answers quickly and can look into the recap's
  articles"; built, NOT deployed, owner has not yet approved the look).** A pill "Talk about it" in the Daily recap card's header
  (`.rtalk`, shown only when `live/talk.js` loaded) opens the same card (`tkShowCard({recap: day})`, `TK.recap`) over the recap card.
  The guide is a SEPARATE, small one: `live-token` gets `{recap: "YYYY-MM-DD", lang, style}` instead of `story_id`, reads ONE row of
  `recaps` (kept 10 minutes in the function), and `recapbrief.ts` (pure, tested) gives the model only the recap's own lines: per story
  `[s<id>] headline | N outlets`, `SUMMARY (STATUS)` = the brief sentence, `MORE (STATUS)` = the article's opening sentences. About
  2,000-4,000 words for a day against 1,000+ sentences for the full articles; no GitHub fetch, no per-article fetch. The price: it
  cannot answer beyond the opening of a story; its rules say so and send the reader to tap the story's line (a tap opens the
  article; the conversation ends with the recap card). Rules are shorter than the article guide's and have no "Shall I go on?"
  (a section/day question names at most five stories and says how many are left). `highlight("s<id>")` lights that story's bullet
  (`.rs.lit`); same function and parameter name as for an article, described differently by `toolsFor(nb, "recap")`. Counted like
  any conversation (same hourly/daily/concurrent limits) as `live_sessions.story_id = 0`: **migration
  `20261012000100_live_talk_recap.sql` must be applied before deploying `live-token`** (it only changes `live_talk_begin`'s
  existence check for story 0). Intro: its own words (`live/intro.json` `recap_en`/`recap_hi`: "...about today's news?") and its own
  recordings `intro-recap-<Voice>-<lang>.m4a` (`python -m nishpaksh.live_intro`, or the `live-intro` workflow, now makes both
  kinds; 20 more files, 2 TTS calls each, run again the next day if the quota ends); a voice without one: the guide says the words
  itself (slower start). The card sits above the bottom sheet through `html.talk-recap` (z-index) and the recap card keeps its own
  back-button entry (back closes the recap card and ends the conversation, it does not just minimise). Tests:
  `tests/live/recapbrief.test.mjs`, `tests/live/recaptalk.test.mjs`. Not measured: speed on the real model (compare "talk timing" for the
  same question in an article and in the recap), how well it follows the "at most five" rule, Hindi wording.
- **Not done / later:** the design and name; voice search with `3.5 Transcribe Live`; session resumption (a conversation is
  capped at 8 minutes, Live audio sessions at 15, so it is not needed yet); analytics of how long people talk.

### Talk to the article: the design (owner, Oct 11 2026; in `site/index.html`, block "Understand by talking")
- **Button:** a third circle in the article's audio/video row (same 52 px white circle, shadow and indigo icon), pushed to the
  far end; a speech bubble with voice bars. Hidden unless `live/talk.js` loaded (`html.talk-on`), so a missing module
  never shows a dead button. The module is loaded in the background 0.7 s after the page starts, so the first tap can start sound
  at once (browsers only let sound and microphone start inside a tap).
- **Banner:** 1.15 s after an article has opened, a pill grows out of the button to the video button (clip-path, the
  text fades in after), stays 4.8 s, folds back in. Once per opening; not while a conversation exists. Tapping it = tapping the button.
- **Card:** centred (340 px), article blurred behind (`.tkveil`), light blue glow while talking. Collapse top-left, close
  top-right. Eleven bars: dance while the guide speaks, follow the reader's voice (`onLevel`) while listening, wave while connecting.
  The guide's last words show as a caption. A privacy line is always on the card (see Privacy above). Not signed in: the
  sign-in card opens (with its own reason line), then the card opens in "ready" with a Start button: a fresh tap, as iOS needs.
- **Collapse:** the card shrinks into a translucent floating button. At the top of the article it glides onto the article's
  own button (takes its white look, so the swap is invisible); when that scrolls under the header it glides to the bottom right
  (above the audio player when that is showing). Following is exact while near (< 32 px), a chase with ease when far.
  It shows a voice and a pulse ring while the guide speaks. Tapping it opens the card again.
- **Ends the conversation:** close (X), leaving the article, opening another one, switching language (the guide was briefed in
  the other one), playing the read-aloud, the conversation ending by itself (45 s quiet, 8 min, server goAway; the reason is
  said on the card, or as a toast when collapsed). Starting pauses the read-aloud. Phone back / Escape collapses the card first.
- **The model's highlight** lights `.sent.lit` (the read-aloud's own style) and scrolls to it. The card blurs the article, so
  the reader sees it when collapsed (or faintly through the blur).
- **Served from:** `live/talk.js` and `live/intro.json` are copied to `/live/` by `site.yml` (and `live/intro-*.m4a` when
  they exist). Locally: `cp -r live site/live` (git-ignored) and serve `site/`.
- **Fixed in `live/talk.js`:** closing while connecting (permission box up, token being fetched) used to carry on: it opened the
  microphone and the socket after the stop. Each `start()` is now a run that checks it is still wanted after every wait
  (3 tests in `controller.test.mjs`).
- **Browser tests:** `tests/talk_ui/` (Playwright, mock module; README there). 32 checks, run by hand, not in CI.
- **Voice and pace (owner, Oct 11 2026: "give the options to the user; the default is how an Indian speaks").** A "Voice and pace"
  link on the card opens a panel (the left button becomes a back arrow): **voice** (the 10 Gemini voices Google's docs list with a
  descriptor: Kore, Orus, Zephyr, Autonoe, Umbriel, Erinome, Laomedeia, Schedar, Achird, Sadachbia), **pace** (slower / natural /
  faster), **tone** (warm / newsreader), **English accent** (Indian / neutral). Kept in `localStorage` (`np-voice`), sent as `style`
  with every start. Defaults: Kore, natural, warm, Indian English. Gemini has NO speed, accent or tone setting, only the voice and
  a language code, so the last three are WORDS in the instruction: `voice.ts` `voiceBlock()` (pure, tested), placed before the
  article, after the rules, and it says it never loosens them. Its fixed part is what an Indian listener expects whatever was
  chosen: Indian names and places said the Indian way, lakh and crore and rupees (never millions or dollars), natural north-Indian
  everyday Hindi with common English words said as in Hindi conversation, Hinglish mirrored. `cleanStyle()` checks every field against
  a fixed list (strings only: `["indian"]` once slipped through `String()`), so request text can never reach the model.
  Pace, tone and accent also apply LIVE: `talk.nudge(text)` sends a short `realtimeInput.text` ("From now on, speak slowly"),
  held until the guide is listening so nobody is cut off. The voice only changes with the next conversation (it is in the setup message).
  The function returns `voice`, and `language_code` (hi-IN, en-IN, or en-US for the neutral accent) ONLY when the secret
  `LIVE_LANGUAGE_CODE` is `1`: native-audio models pick the language themselves and may refuse a code. Off until tested.
  **Not verified (needs the real model, by ear):** whether each voice follows the pace/tone/accent words in Hindi and English; whether a
  mid-conversation nudge is obeyed and whether the guide answers it aloud; whether `en-IN` is accepted; which voices suit news.
  No voice preview (it would cost a conversation).
- **Not verified:** a real phone (iOS Safari especially: sound start, the card's blur, `scale`/`inset` clip-path support),
  the glide at 60 fps on a mid-range Android, real Hindi wording by a native reader, the banner against the real Hind font
  (tested with a fallback face, wider than Hind).

- **The guides open other articles by themselves (owner, Oct 13 2026):** the article's guide and the recap's guide both have a second function, `open_article(story_id)` (`brief.ts` `OPEN_ARTICLE`, declared in `toolsFor` for both kinds). The recap's lines already carry every story's number (`s<id>`); the article's guide gets a list `OTHER STORIES TODAY` (`[a<id>] how long ago | outlets | headline`, newest 40 of today's IST day, `otherstories.ts`, from the site's feed file `<lang>.json` with a 2 s timeout; no list = it is told it cannot open others). The function is an ordinary blocking one, never answered SILENT: `talk.js` `LiveProtocol._tools` hands it to the page (`on.open` = `openArticle`), which asks `live-token` with `{open: id, lang}` (public text, no login check, no count, `articleDigest(.., 80, "OPENED ARTICLE")`), keeps it per conversation (never fetched twice), and sends the text back as the answer; a failure is told to the guide in words. While it loads, a recorded filler line (`filler-<Voice>-<lang>-1..4.m4a`, words in `live/intro.json` `filler_en` / `filler_hi`, made by `python -m nishpaksh.live_intro --kind filler`, or Actions -> live-intro with kind `filler`; 80 files, 1 speech call each) plays and the guide's answer follows it; no recording for a voice = silence until the answer. The card shows "Reading: <headline>" (`TK.reading`, `onArticle`). The watchdog does not nudge while an article is being fetched. Tests: `tests/live/opentalk.test.mjs`, `tests/live/otherstories.test.mjs`, `tests/talk_ui/flow_reading.cjs`, `tests/test_live_intro.py`. NOT verified on the real model: that it calls `open_article` only for depth questions, the total delay, and that the Live model accepts a function answer arriving a second or two after the call. Deploy: `live-token`, publish the site, then run `live-intro` with kind `filler`. A native Hindi reader should check the Hindi filler lines.

## Context placement: "Also in these reports" (owner, Oct 13 2026)
The Background of a protest-site story held a harassment complaint, a cricket story's Background a bowler's record,
and paragraphs mixed unrelated facts. Rebuilt, keeping the Oct 8 rule (never lose something important) by DEMOTING, not dropping:
- `belong.check`: every background / related / explanation line gets one fixed-choice answer (history, lead-up, explains,
  linked, other) against the story's news, asked twice (second time reversed), cached in `analysis.context_tags`.
  Agreeing answers decide; answers differing in KIND decide `other` (the safe answer); fewer than two answers (quota,
  no model) move nothing. history vs lead-up is settled by CODE from the date (within 14 days before the news = lead-up).
  A "background" line dated after the news becomes a related event. Reactions and "what next" are never asked.
- `other` lines go to `payload["also"]`, not the writer, not the completeness bar. `narrative._finish` turns them into
  `narrative.other_coverage` (plain lines with colour and source numbers); the site shows them in a collapsed
  "Also in these reports" under the article, one line each, never a paragraph. No topic labels yet (decided: none).
- Background slots (`plan.py`): history first, then lead-up, each oldest first, never in one paragraph.
- One subject per paragraph: `belong.assign_topics` (one `dupes.topics` call, cached in `analysis.topic_groups`) puts a
  `topic` on every statement; `plan._by_topic` splits a section's chunk by topic and `_pack(topical=True)` closes a
  paragraph only at MAX_STATEMENTS. No topics (call failed): the word-based `_cluster` as before.
- Hindi: `compose.translation_problem` (ported from booktrans.py's output_problem) rejects empty, echoed, non-Devanagari
  and number-changed translations; they are not cached.
- Only new articles get this: published ones are closed.

- **Refresh button alert (owner, Oct 14 2026).** `manualRefresh` compares the newest card time before and after the reload.
  No newer card: a short tooltip ("No new articles yet", every press) and a one-time alert is asked for (follow `next|any`,
  signed-in readers; `setNextAlert`). A newer card: the deck goes to the top (`jumpTo(0)`) and the alert is cancelled. Only the
  last press counts (calls are chained). `notify.queue_articles` sends it for the first article published after the follow
  was made (`reasons(..., at=)`), once per reader per run, then deletes the follow. Migration `20261014000100_follow_next.sql`
  must be applied before the site is deployed (the follows table only allowed 5 kinds). `sw.js` np-main-37.
- **Writer: falling bar, drafting in parts, resting models (owner, Oct 16 2026).** A story is never given up:
  `narrative.publish_bar(tries)` is 80%, 75%, 70% ... down to `PUBLISH_FLOOR` 50% of every statement, `tries` being
  `writer_failures.n` (it now adds up across statement sets). `essay_ok`/`essay_shortfall` take the bar. A kept draft that
  already meets this try's bar skips the fill passes (`write_narrative(bar=)`), so it publishes with no new writing. At the
  floor, the same statements are tried again only every `compose.FLOOR_WAIT_HOURS` (3); new statements at once. Outcome
  "writer tries used up" is gone ("resting at the lowest bar"). A story with more than `PARTS_OVER` (14) statements is drafted
  part by part (`_draft_in_parts`, `parts_of`: whole plan paragraphs packed to ~`PART_SIZE` 10 statements, each call sees the
  article so far), then the fill passes as before. Router: an overloaded model in `REST_TIERS` (writer, quality) RESTS on
  every key for 2, 4, 6 ... 10 min (`REST_STEP`, `REST_MAX`) instead of being dropped for the run (`router.rested`, in the
  desk report); other tiers still drop. So the desk's `refused_last_run` no longer skips Flash writer models.
- **Updates since published = struck lines only (owner, Oct 16 2026).** `editions.attach_updates` lists an update only once
  the page's line it replaces is struck; the site lists the LATER line (`text`, in its colour), one row per struck line
  of the article (`data-replaces`). A struck line in the article (`data-struck`, its statement ids) jumps to its row. Follow option "struck through" (follow kind 'colour', key "struck"): `notify.line_classes` marks struck
  lines "struck" and `queue_colours` counts lines newly struck. No migration. `sw.js` np-main-60.
- **Desk order:** a story refused as a follow-up before (`edition.followup.ok` False) goes after every other ready story.
- **Entity table ADOPTED for shortening (Oct 25 2026, after two shadow runs on 66 live articles).** `style.people` now returns
  `EntityTable.shortenable()` (`style.USE_ENTITIES`; any failure falls back to `_people_old`, kept for the shadow comparison).
  Run 1 found bodies and events judged people (US Geological Survey, Jamiat Ulema-e-Hind, BCCI Women, an exercise), title-like
  words kept in names (Commissioners, Capt, Shree, Free, Communications), a doubled name, a place leaking after "of", and
  order-dependent clustering; run 2 (after fixes): 51 names gained (all people except "Modi Sarkar" / "Narendra Modi Sarkar",
  fixed by BODY_WORDS), 11 "lost" of which most are bodies or the old code's title-in-name strings, Rahul Gandhi lost correctly
  (Priyanka Gandhi Vadra is in the story), Ajinkya Mirgul unexplained (the report now prints kind and evidence for each lost
  name), one cautious split left (story 40418: "Lokesh Shatrujeet Kapoor" cannot be "Shatrujeet Singh Kapoor"). NOT adopted
  yet: `voice.speaker_key` (context-free, used in ~30 places; the table's `speaker_key` needs a per-story table passed in).

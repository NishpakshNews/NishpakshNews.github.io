# Nishpaksh construction register — draft 0.1

> Planning document only. Based on the owner-supplied `NOTES(1).md` (compacted 2026-10-18) and prior conversation. These are **candidate work items**, not a claim of complete requirements, proven implementation, or measured algorithm superiority. Preserve original IDs; do not silently collapse findings, engineering fixes, and literature suggestions. This document lives on a planning branch, not `main`.

## Decision rules

1. No implementation starts until the specific unit is named, its contract defined, its affected stages mapped, and its dependencies made explicit.
2. Follow upstream-to-downstream data flow when dependencies permit; do not force arbitrary phases or pretend all units of a type must precede another type.
3. For each proposed algorithm: name the established tradition, its incumbent, interface, expected failure mode, abstention rule, resource requirements, and deployment fallback.
4. Distinguish hard safety invariants (evidence independence, source IDs, conflict treatment, published verification status) from presentation optimization (fewer repeats, smoother prose). Reader deduplication must not raise corroboration.
5. The encrypted newsroom owns dossiers and evidence. The public repository must not contain private source text, newsroom exports, secrets, or per-story private traces. Writer code cannot consume the private dossier.
6. Only feature/planning branches; no direct edits or merges to `main`. Prefer reviewable small PRs. No production behavioral change without regression tests, appropriate fail-closed behavior, and rollback path.
7. Comparative hypothesis testing is deferred until the resulting integrated system has operated and produced useful traces. This does **not** defer schema tests, deterministic examples, pipeline smoke tests, regression checks or CI.
8. Mark proposals as **unexamined / designed / implemented-on-branch / safety-checked / operated / experimentally compared**, not simply “done.”

## A. Build recommendations — source IDs B1–B34

Each B item may expand to several contracts or algorithms. “Links and prerequisites” are **proposed**, inferred from the descriptions, and require confirmation during design.

| ID | Named construction unit | Links and prerequisites | Boundary / intended result |
|---|---|---|---|
| B01 | Entity resolution and entity linking | S11 S20; B02 B08 B22 | Per-story entity IDs, mention resolution, and cannot-link constraints |
| B02 | Structural alias detection | B01; S08 S11 | English/Hindi apposition and alias evidence; proposals never override constraints |
| B03 | Evidence-span grounding and cross-lingual faithfulness | B10 B22; S13 | Number source sentences and preserve exact supporting spans for each extracted claim |
| B04 | Verbatim quotation and speech attribution | B03 B22 | Quotation marks only for independently checked source spans |
| B05 | Temporal graph and ordering | B15; S09 S14 | Anchor time, encode event precedence, topologically order article events |
| B06 | Reader-side redundancy separate from corroboration | B01 B08 B16 | Loose presentation grouping must not increase verification-source counts |
| B07 | Slot-value conflicts and contradiction | B01 B03 B05 B22; S13 | Compare actor, place, date, number, polarity and attribution slots |
| B08 | Text and quantity normalization | B10 | Canonicalize units, currency, case, whitespace and equivalent representations conservatively |
| B09 | Discourse model and article-level inspector | B01 B05 B06 B18; S28 | Track introduced entities, already-stated facts and chronology throughout article |
| B10 | Source text hygiene and language profiling | S27 optional | Decode publisher bytes, repair mojibake and profile language/script; PR #1 covers only initial decoding and repair |
| B11 | Private per-story decision dossier and export | E05 E09 | Append stage decisions, defaults and lost/kept records in encrypted newsroom, never public |
| B12 | Bilingual lexicon learner hygiene | B03 B31 | Induce translations with association strength and exclude competing rendering errors |
| B13 | Corpus-derived IDF and word weighting | B10 | Replace hand stopword lists with corpus-weighted lexical signals |
| B14 | Robust topic grouping | B13 S28 | Separate paragraph themes from claim candidate generation, degrade gracefully on quota failure |
| B15 | Shared event-type ontology | B03 B22 | Stable event type shared by matching, ordering, headline and coreference |
| B16 | Claim-deduplication pipeline | B01 B08 B13 B15 B22; S07 S08 S12 | Blocking, pair scoring, constrained clustering, strict corroboration vs loose reader grouping |
| B17 | Name-conflict resolution | B01 B02 B05 B07 B15 B16 | Distinguish aliases, different people, conflicting reports and unrelated events |
| B18 | Referring-expression generation | B01 B09 | Select full name, unique surname, role or pronoun from discourse state |
| B19 | Evaluation harness and comparative experiments | B11 | Preserve T1–T5 and owner labels; deferred comparison after system operation, with basic regression checks during builds |
| B20 | English/Hindi translation quality | B03 B12 | Source alignment, reference-free quality estimation, constrained generation and fidelity checks |
| B21 | Cross-document event coreference for matching | B01 B05 B16; S07 S08 S12 | Retrieve, score, and cluster matching events across sources |
| B22 | Factuality and attribution schema | B03; S01 S10 | Structured source/polarity/certainty with unknown rather than invented defaults |
| B23 | Long-document reading | B01 B03; S02 S03 | Carry entity state across chunks and remap relations after consolidation |
| B24 | Reliable model/fetch call layer | E04 E06 E14 | Tri-state results, retry classes, TTL, circuit breaker, queue and budget handling |
| B25 | Truth-discovery verdict modeling | B07 B22 B28; S15 | Discount source copies and combine independently attributed support and denial |
| B26 | Evidence-grounded verification judge | B03 B22 B24; S16 | Require retrievable identified evidence and entailment/contradiction before strong verdicts |
| B27 | Clause-level atomic fact splitting | B03 B22; S17 S18 | Syntax-based split proposals and semantic preservation checks |
| B28 | Source independence and canonicalization | B01 B10; S04 S19 S20 | Detect reused text and shared upstream origins by stable source IDs |
| B29 | Check-worthiness and fact/characterisation classifier | B22; S21 | Calibrated classifier with abstention; never treat uncertain judgment as fact |
| B30 | Latent-position perspective model improvements | S22 S24 S25 | Reuse existing positions model; align gating, clustering, propensity and null checks |
| B31 | Cross-lingual framing lexicon | B12; S23 | Language-independent concept IDs for framing and loaded-language patterns |
| B32 | Background relevance retrieval | B13 B16; S26 | Rank context against story facts and abstain on weak associations |
| B33 | Sidebar and boilerplate block classification | B10; S27 | Prevent unrelated page navigation/related-story blocks entering extraction |
| B34 | Development-thread linking | B05 B13 B21; S07 | Retrieve candidate story parents, classify same vs development, preserve typed edges |

## B. Engineering fix ledger — E1–E41

These are code/data-contract fixes, **not** themselves named technical algorithms. Original IDs are retained even when one is part of a larger B system.

| ID | Named fix | Related build units |
|---|---|---|
| E01 | Validate enumerated model responses; unknown instead of silent defaults | B22 |
| E02 | Collision-proof claim/context/piece IDs | B03 B23 |
| E03 | Remap every relation endpoint through duplicate merge | B23 |
| E04 | Failure taxonomy, negative-cache TTL, retries and backoff | B24 |
| E05 | Append-only dossier, read statistics and drop/default trace | B11 |
| E06 | Yes/no/unknown result contract; cache answered pairs only | B24 B16 |
| E07 | Store attribution separately from proposition | B22 |
| E08 | Record scoring parameters and their provenance | B11 B19 |
| E09 | Export time, canonical IDs, stance and failure counters | B11 |
| E10 | Record skipped long-document characters | B11 B23 |
| E11 | Protect evidence-set verdict from arithmetic overwrite; rejudge on added evidence | B25 B26 |
| E12 | Hysteresis and reason for corroboration 6-hour clock reset | B25 |
| E13 | Keep relation capitalization and suppress missing endpoints | B27 |
| E14 | Retry incomplete second opinions fairly | B24 B26 |
| E15 | Refuse corroborated verdict on defaulted stance | B22 B25 |
| E16 | Check lexical coverage when splitting claims | B27 |
| E17 | Record split outcomes and rejected reasons | B11 B27 |
| E18 | Track inherited fields and transactional relation rewrite on split | B27 |
| E19 | Count originality only for actually answered non-matches | B28 |
| E20 | Guard dateline parsing with place/date/agency evidence | B28 |
| E21 | Closed vocabulary and canonical ID for governments | B01 B28 |
| E22 | Version and refresh checkability judgments | B29 |
| E23 | Shrink sparse perspective-agreement ratios | B30 |
| E24 | Count independent read outlets, and hysteresis of qualifications | B30 |
| E25 | Preserve last good perspective clusters and report stability | B30 |
| E26 | Rotate failed concepts with bounded retries and stemming | B31 B24 |
| E27 | Share one generic-author definition | B28 B30 |
| E28 | Deduplicate stance rows, treat unknown/default as missing | B30 B22 |
| E29 | Timestamp/freshness checks for position-gate reports | B30 |
| E30 | Report propensity and null-distribution diagnostics | B30 |
| E31 | Distinguish no signal from failed/unknown report | B30 |
| E32 | Normalize and count unparsed theme/tag responses | B14 |
| E33 | Cache belong decisions by text AND news context | B14 B32 |
| E34 | Must-link closure and deterministic grouping | B14 |
| E35 | Preserve duplicate occurrence identity across cache hits | B14 B16 |
| E36 | Instrument belong counters and ordered placement | B11 B14 |
| E37 | Retain stored story parents on model failure | B34 |
| E38 | Merge overlapping parent links transactionally | B34 |
| E39 | Cache thread search against actual candidates | B34 |
| E40 | Review unused created query/column before non-destructive removal | B34 |
| E41 | Store typed development/same edges with stable tie-breaking | B34 |

## C. Technical systems and algorithms — S1–S28

These are candidate algorithm families from the notes, **not** a command to implement every alternative. S05 is superseded and S22 is revised.

| ID | Named established-method candidate | Related build units |
|---|---|---|
| S01 | Event factuality and source attribution | B22 |
| S02 | Long-document coreference and bounded entity memory | B23 |
| S03 | Correlation clustering and MMR survivor selection | B23 B16 |
| S04 | Text-reuse alignment and diverse-source selection | B28 |
| S05 | Superseded: event-log design moved to E05 | B11 |
| S06 | Budgeted maximum coverage for Tavily fetches | B24 |
| S07 | Cross-document event coreference, retrieve-and-rerank | B21 B34 |
| S08 | Probabilistic record linkage with reject option | B16 B21 |
| S09 | TimeML/TIMEX3 temporal anchoring | B05 B21 |
| S10 | Proposition-level comparison including attribution/modality | B22 B16 |
| S11 | Multilingual NER and constrained entity linking | B01 B02 |
| S12 | Noisy-label aggregation (Dawid–Skene/MACE) | B16 B21 B26 |
| S13 | Textual entailment and QA consistency | B03 B07 B20 B26 |
| S14 | Learned contrast/temporal features | B05 B16 |
| S15 | Truth-discovery/source-reliability aggregation | B25 |
| S16 | Retrieve-then-verify with identified-source evidence | B26 |
| S17 | Syntactic atomic-fact decomposition | B27 |
| S18 | Bidirectional NLI and attribution-scope preservation | B27 |
| S19 | Copy-based source independence | B28 |
| S20 | Source canonicalization through entity linking | B28 |
| S21 | Check-worthiness/subjectivity classification | B29 |
| S22 | Revised: existing ideal-point model becomes clustering source of truth | B30 |
| S23 | Cross-lingual framing concept lexicon | B31 |
| S24 | Nuisance-factor item response theory | B30 |
| S25 | Fixed-margin null model | B30 |
| S26 | Background-link relevance retrieval/ranking | B32 |
| S27 | Sidebar/boilerplate block classification | B33 |
| S28 | Theme clustering with must-link constraints | B14 |

## D. Cross-cutting ideas in the notes not yet resolved into unique work items

Do not silently discard unnumbered recommendations: grammatical error correction/LanguageTool; dependency parsing, POS and morphology; neural coreference versus deterministic bounded-memory alternatives; bridging-anaphora resolution; centering/entity-grid discourse coherence; semantic-role labeling or AMR; headline-to-article factual consistency and novelty detection; learning-to-rank for headlines/story pick; event-type induction and event scripts; cross-lingual sentence alignment and translation QE; bilingual lexicon induction; constrained text generation; referential and quote checks; source selection as submodular optimization; active-learning approval for uncertain aliases; language/script profiling; audit diagnostics. These must be reconciled against B/E/S before any is discarded or elevated into a distinct contract.

## E. Initial non-phase dependency view

- Ingestion truth boundary: B10, B33, B24, B11, then B03/B22/B23; feed quality must be visible before claims are trusted.
- Shared representation backbone: B01/B02, B08, B15 and B05 provide stable entities, values, event types and time for downstream matching.
- Matching and evidence backbone: B16/B21, B28, B07, B17, B25/B26; reader redundancy B06 is a separate, less strict client of similarity decisions.
- Composition/reader backbone: B14/B32, B09/B18, B20, B05, B34; do not hide upstream evidence defects with stylistic editing.
- Cross-cutting analysis and quality: B11 (dossier), B19 (future comparisons), B29, B30/B31, B12/B13. These connect at their own input boundaries; they are **not** a final phase.
- Each dependency is provisional until the exact existing code/data contract is inspected on the corresponding branch.

## F. Per-unit construction decision record — required before implementation

- **Identity:** construction-unit ID, source B/E/S/F references, problem statement and example failure.
- **Inputs/outputs:** exact types, provenance, polarity/unknown semantics, storage lifetime, privacy.
- **Invariants:** what must remain true; particularly “cannot-link,” independent origins, verdict safety, quotation fidelity.
- **Baseline:** existing files/functions, current behavior proven by code, what will be replaced and what will remain.
- **Algorithm selection:** established named alternatives, why selected, dependencies, resource/quota budget, fallback and reject/unknown behavior.
- **Failure semantics:** timeout, invalid JSON, missing source, quota exhaustion, stale data, model disagreement and retry.
- **Changes:** target branch, smallest reviewable patch, migration compatibility, shadow/disabled configuration where appropriate.
- **Checks:** deterministic regression cases and CI needed before branch integration (not delayed hypothesis experiments).
- **Later evidence:** emitted counters, dossier records, operational observation window, comparison question and owner decision.
- **Status:** design needed / designed / coding / safety-checked / operating / later hypothesis assessment.

## G. Current branch status and sequence rule

- `planning/construction-register-20261021`: this register only; not intended for deployment.
- `engineering/source-text-hygiene-20261021`: existing PR #1 is a **partial B10 implementation**. It is still a draft and unmerged; its unit needs to be reconciled with this register, tests run, and decisions reviewed.
- Do not decide “all engineering fixes first” or “all advanced algorithms later.” Instead, inspect a **single next dependency-ready construction unit**, define its contracts, implement its safety foundations and algorithm together as appropriate, then proceed to the downstream consumer.
- No commits or merges to `main` are authorized by this register.

## H. Inventory reconciliation still required

This is **draft 0.1, not an exhaustive canonical specification**. To finish naming *everything*, cross-check each B/E/S row against the numbered F findings, hypotheses, unnumbered technical proposals, and current `main` implementation. Deduplicate by behavior rather than by name. For each item mark **keep separate, component-of, alternative-to, superseded-by, or not yet named**. The prior conversation sometimes assumed the harness must precede every change; the owner has now decided that comparative hypothesis testing follows a period of operation, while engineering safety checks stay immediate.

# What the learners find, and what you do with it

Three learners read the outlets every hour and remember what they see in the newsroom (never in this public
repository). A devil's advocate checks every candidate and can only hold or block it, never approve it. You decide
only in the files below; nothing else needs your attention.

| Learner | File you look at | What happens without you |
|---|---|---|
| Titles ("Skipper", "Commissioner") | `titles_proposed.yaml` | Nothing. Titles are never learned on their own. |
| Synonyms ("unprecedented" = "historic") | `synonyms_learned.yaml` | Pairs that pass are learned and used for matching. |
| Terms (flood = बाढ़) | `glossary_learned.yaml` | For now nothing: every pair waits in `proposed:`. |

## Titles: `titles_proposed.yaml`

- **Approve:** move the line from `proposed:` into `titles_learned.yaml`, under `roles:`.
- **Refuse:** add the word to `rejected:` at the top of `titles_learned.yaml`. It is never proposed again.
- **Never, whatever the counts:** add the word to `never_titles:` in `devils_advocate.yaml` (Pappu is there).
- `review:` lists approved titles the devil's advocate now objects to. Nothing changes by itself; look again.

## Synonyms: `synonyms_learned.yaml`

- **Wrong pair:** delete its line and add its two words as one line to `rejected:` ("killed murdered").
- **Keep two words apart everywhere:** add them to `never:` in `synonyms.yaml`.
- A learned pair the devil's advocate later objects to is taken out of the file by the job.

## Terms: `glossary_learned.yaml`

- **Approve:** move the line from `proposed:` to `terms:`. From the next run, our Hindi pages use that rendering.
- **Refuse:** add the English word to `rejected:`. A refused term also leaves `terms:`.
- `why:` on a proposal says why it waits: a clean pass, a competing Hindi rendering, or evidence that rests on one
  day or one outlet.
- To let clean pairs be learned without you, set `AUTO_LEARN = True` in `nishpaksh/learn_glossary.py`.

## Your own entries

- Names: `names.yaml` (a person's spelling in both languages; always wins).
- Terms we must always use: `terms:` in `glossary.yaml` (always win over learned ones; changing one re-translates).
- Cue words the devil's advocate looks for: `devils_advocate.yaml` (add freely: they can only hold or block).

## How to see what is happening

The hourly log has one line per learner: "title candidates", "synonym candidates", "glossary candidates", each
counting where candidates stop (sources, days, people, an anchor outlet, the devil's advocate). The `audit` workflow
replays all three over the last 14 days and stores the counts and the near misses in Supabase (`diagnostics`, kind
`audit`, field `learners`).

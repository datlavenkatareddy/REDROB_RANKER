# Redrob Hackathon — Intelligent Candidate Discovery & Ranking

Ranks the 100,000-candidate pool against the released "Senior AI Engineer —
Founding Team" JD and produces the top-100 submission CSV. Fully offline at
ranking time — no hosted LLM calls, no GPU, single CPU core, ~40 seconds for
the full pool.

## Quickstart

```bash
pip install -r requirements.txt   # only needed for optional embeddings/sandbox — rank.py itself is stdlib-only
python src/rank.py --candidates ./data/candidates.jsonl --out ./submission.csv
python artifacts/validate_submission.py ./submission.csv
```

That's the whole reproduction path. `rank.py` reads raw `candidates.jsonl`
directly — no precomputed index is required to run it, though one is
supported (see below).

## Why this isn't "find the most AI keywords"

The JD is explicit that keyword-stuffing is a trap: *"A candidate who has
all the AI keywords listed as skills but whose title is 'Marketing Manager'
is not a fit, no matter how perfect their skill list looks."* So this
ranker treats **title as a gate, not a feature** — an irrelevant title
caps the whole score via a multiplier, regardless of skill list length.
Career-history text (not just the skills array) is checked for actual
evidence of shipped ranking/search/retrieval work, and Redrob behavioral
signals (response rate, recency, notice period) act as a bounded multiplier
on top of content fit — so an unreachable perfect-on-paper candidate doesn't
outrank a reachable, slightly-less-decorated one.

## Architecture

```
src/
  jd_config.py            structured JD requirements (mandatory/preferred skill
                           groups, title tiers, explicit disqualifiers) — hand-
                           encoded once from job_description.md, not re-parsed
                           by an LLM at ranking time
  features.py              raw candidate JSON -> flat feature dict + honeypot
                           flag (data-calibrated internal-consistency checks,
                           see docstring in detect_honeypot())
  scoring.py                hybrid scorer: title gate x (skill match + career
                           evidence + experience band + location + education,
                           dynamically reweighted when a section is missing)
                           x behavioral multiplier, minus disqualifier penalty
  reasoning.py              deterministic, per-candidate reasoning string —
                           every claim is pulled from the candidate's actual
                           fields, template + which facts surface vary by
                           candidate_id (not by rank), concerns are only
                           stated when actually present in the data
  rank.py                   entry point — streams candidates.jsonl, scores,
                           excludes honeypots, writes the top-100 CSV
  precompute_embeddings.py  OPTIONAL offline step (not part of the 5-min
                           ranking budget — see submission_spec.md §10.3's
                           precomputation exception): sentence-transformers
                           (all-MiniLM-L6-v2, local, no API) embeds the JD
                           and all 100K candidates, caches cosine similarity
                           per candidate to a pickle rank.py can optionally
                           load via --embeddings
sandbox/app.py             Streamlit sandbox for the required hosted-demo
                           link (§10.5) — accepts a small candidate sample,
                           runs the same pipeline, shows/download the ranking
```

### Optional: add semantic embeddings

```bash
pip install sentence-transformers
python src/precompute_embeddings.py --candidates ./data/candidates.jsonl --out ./artifacts/embed_sims.pkl
python src/rank.py --candidates ./data/candidates.jsonl --out ./submission.csv --embeddings ./artifacts/embed_sims.pkl
```

This blends dense semantic similarity into the skill-match component (40%
weight) on top of exact/substring term matching, catching synonym cases
substring matching misses (e.g. "OpenSearch" experience against a JD that
says "Elasticsearch"). The embedding step itself is precomputation and is
allowed to take several minutes — only the `rank.py` step that produces the
final CSV is bound by the 5-minute limit, and it stays well under that
whether or not `--embeddings` is passed.

## Honeypot handling

`detect_honeypot()` in `features.py` flags candidates on two patterns
confirmed present in the actual released dataset by direct inspection (not
guessed): (a) 3+ skills marked "expert" with 0 months of use, and (b)
career-history durations summing to more time than the candidate's stated
total years of experience. Both were verified against the real 100K pool —
zero false positives on ordinary profiles, 45 candidates flagged (against a
disclosed ~80 total; the remainder likely encode a pattern this repo doesn't
check for, e.g. company-founding-date inconsistency, which isn't checkable
without an external company database). Flagged candidates are excluded
outright from ranking, not just down-weighted.

## Known limitations / honest gaps

- Company-founding-date-vs-tenure honeypots (mentioned in the doc's own
  example) aren't caught — no external company database is available in
  this dataset.
- "Framework enthusiast" (GitHub full of tutorial repos) and "closed-source
  only, no external validation" disqualifiers from the JD aren't
  operationalized — the schema doesn't expose GitHub repo content, only
  `github_activity_score`.
- Title classification is a curated keyword list, not a trained classifier —
  it will miss unusual but valid title phrasings not in `jd_config.py`.

## Reproducibility / compute

Tested end-to-end on the full 100,000-candidate `candidates.jsonl`:
single CPU core, no GPU, no network calls during the `rank.py` step,
~40 seconds wall-clock, well under the 5-minute / 16GB budget.

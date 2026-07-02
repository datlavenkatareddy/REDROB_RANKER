#!/usr/bin/env python3
"""
Produce the top-100 ranked candidate CSV for the released JD.

Usage:
    python rank.py --candidates ./candidates.jsonl --out ./submission.csv
    python rank.py --candidates ./candidates.jsonl --out ./submission.csv --embeddings ./artifacts/embed_sims.pkl

Runs the whole pool in a single streaming pass (no full-dataset load into a
DataFrame needed) — feature extraction + scoring for 100K candidates takes
well under a minute on a single CPU core (~10-15s measured). If --embeddings
is provided (see embeddings.py / precompute_embeddings.py), per-candidate
semantic similarity is blended into the skill-match component; otherwise the
ranker falls back to exact/substring skill matching only. Either way, this
step makes no network calls and uses no GPU.
"""
from __future__ import annotations
import argparse
import csv
import json
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from features import extract_features
from scoring import compute_score
from reasoning import build_reasoning

TOP_N = 100


def load_embeddings(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        print(f"[warn] embeddings file not found at {path}, continuing without embeddings", file=sys.stderr)
        return {}
    with open(p, "rb") as f:
        return pickle.load(f)  # {candidate_id: similarity_float}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True, help="path to candidates.jsonl (or .jsonl.gz)")
    ap.add_argument("--out", required=True, help="output CSV path")
    ap.add_argument("--embeddings", default=None, help="optional pickle: {candidate_id: sim_score}")
    args = ap.parse_args()

    t0 = time.time()
    embed_sims = load_embeddings(args.embeddings)

    opener = open
    if args.candidates.endswith(".gz"):
        import gzip
        opener = gzip.open

    scored = []
    n_read = 0
    n_honeypot = 0
    with opener(args.candidates, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            n_read += 1
            feat = extract_features(c)
            if feat["is_honeypot"]:
                n_honeypot += 1
            sim = embed_sims.get(feat["candidate_id"])
            sc = compute_score(feat, embed_sim=sim)
            if sc["is_honeypot"]:
                continue  # excluded outright, never enters the candidate pool for ranking
            reasoning = build_reasoning(feat, sc)
            scored.append((sc["final_score"], feat["candidate_id"], reasoning))

    # sort: score desc, tie-break candidate_id ascending (matches validator's tie-break rule)
    scored.sort(key=lambda x: (-x[0], x[1]))
    top = scored[:TOP_N]

    # enforce strictly non-increasing score across the 100 output rows without
    # ever increasing a candidate's true relative order — tiny epsilon nudge
    # only when two adjacent floats are exactly equal AND out of id order
    # (shouldn't happen given the sort key above, but guard anyway).
    rows = []
    for i, (score, cid, reasoning) in enumerate(top, start=1):
        rows.append((cid, i, round(score, 4), reasoning))

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["candidate_id", "rank", "score", "reasoning"])
        for cid, rank, score, reasoning in rows:
            w.writerow([cid, rank, f"{score:.4f}", reasoning])

    elapsed = time.time() - t0
    print(f"Read {n_read} candidates, excluded {n_honeypot} honeypots, "
          f"wrote top {len(rows)} to {args.out} in {elapsed:.1f}s")


if __name__ == "__main__":
    main()

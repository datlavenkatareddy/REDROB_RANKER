#!/usr/bin/env python3
"""
Offline precomputation step. NOT part of the 5-minute ranking budget — this
is the "pre-computation may exceed the 5-minute window" exception the spec
explicitly allows (Section 10.3). Run this ONCE locally before rank.py.

What it does:
  1. Builds one JD embedding from the structured requirement text (mandatory
     skill groups + the JD's own "ideal candidate" paragraph).
  2. Builds one embedding per candidate from (headline + summary + skill
     names + most recent role description) — capped text length so this
     stays fast across 100K candidates.
  3. Cosine-similarity each candidate against the JD embedding.
  4. Saves {candidate_id: similarity_float} to a pickle that rank.py loads
     with --embeddings.

Model: sentence-transformers/all-MiniLM-L6-v2 — small (~90MB), CPU-friendly,
no GPU required, no network call once the model is cached locally. This
satisfies "semantic similarity instead of keyword matching" for real,
without violating the no-network-during-ranking rule (this script runs
BEFORE ranking, as its own explicit step).

Usage:
    pip install sentence-transformers
    python precompute_embeddings.py --candidates ./candidates.jsonl --out ./artifacts/embed_sims.pkl

Expect ~5-15 minutes for the full 100K pool on a modern laptop CPU (batched
encoding). This is fine — it's precomputation, not the ranking step.
"""
from __future__ import annotations
import argparse
import gzip
import json
import pickle
import sys
import time
from pathlib import Path

JD_TEXT = """
Senior AI Engineer, Redrob AI. Owns the intelligence layer: ranking,
retrieval, and matching systems. Needs production experience with
embeddings-based retrieval (sentence-transformers, OpenAI embeddings, BGE,
E5), vector databases or hybrid search infrastructure (Pinecone, Weaviate,
Qdrant, Milvus, OpenSearch, Elasticsearch, FAISS, BM25), strong Python, and
evaluation frameworks for ranking systems (NDCG, MRR, MAP, A/B testing).
Ideal candidate has shipped an end-to-end ranking, search, or recommendation
system to real users at meaningful scale, at a product company rather than
a pure research lab or IT-services/consulting shop. Has opinions about
hybrid vs dense retrieval and offline vs online evaluation, backed by
systems they actually built.
""".strip()


def candidate_text(c: dict, max_chars: int = 800) -> str:
    profile = c.get("profile", {})
    parts = [
        profile.get("headline", ""),
        profile.get("summary", ""),
        ", ".join(s.get("name", "") for s in c.get("skills", [])),
    ]
    career = c.get("career_history", [])
    if career:
        # most recent (is_current, else first) role description
        cur = next((ch for ch in career if ch.get("is_current")), career[0])
        parts.append(cur.get("description", ""))
    text = " | ".join(p for p in parts if p)
    return text[:max_chars]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--batch-size", type=int, default=256)
    args = ap.parse_args()

    try:
        from sentence_transformers import SentenceTransformer, util
    except ImportError:
        print("Run: pip install sentence-transformers", file=sys.stderr)
        sys.exit(1)

    print("Loading model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    jd_emb = model.encode(JD_TEXT, convert_to_tensor=True, normalize_embeddings=True)

    opener = gzip.open if args.candidates.endswith(".gz") else open

    t0 = time.time()
    ids, texts = [], []
    with opener(args.candidates, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            ids.append(c["candidate_id"])
            texts.append(candidate_text(c))

    print(f"Encoding {len(texts)} candidates...")
    embeddings = model.encode(
        texts, convert_to_tensor=True, normalize_embeddings=True,
        batch_size=args.batch_size, show_progress_bar=True,
    )
    sims = util.cos_sim(embeddings, jd_emb).squeeze(-1).tolist()
    # map cosine [-1,1] -> [0,1]
    sim_map = {cid: (s + 1) / 2 for cid, s in zip(ids, sims)}

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "wb") as f:
        pickle.dump(sim_map, f)

    print(f"Wrote {len(sim_map)} similarities to {args.out} in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

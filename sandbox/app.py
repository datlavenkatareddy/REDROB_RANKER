"""
Sandbox demo for Stage 1 reproducibility check (submission_spec.md Section
10.5). Accepts a small candidate sample (<=100 candidates as JSONL) and runs
the same rank.py pipeline end-to-end, entirely offline, producing a ranked
CSV in-browser. Deploy this on Streamlit Community Cloud (free tier).

Run locally:
    streamlit run sandbox/app.py
"""
import sys
import json
import io
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from features import extract_features
from scoring import compute_score
from reasoning import build_reasoning

st.set_page_config(page_title="Redrob Ranker — Sandbox", layout="wide")
st.title("Redrob Hackathon — Ranking Sandbox")
st.caption(
    "Upload a small candidate sample (JSONL, one candidate JSON object per line, "
    "matching candidate_schema.json) to see the ranker run end-to-end. "
    "Runs fully offline — no API calls, no GPU."
)

uploaded = st.file_uploader("candidates sample (.jsonl)", type=["jsonl", "json"])

sample_path = Path(__file__).parent.parent / "data" / "sample_candidates_demo.jsonl"

if uploaded is None and sample_path.exists():
    st.info("No file uploaded — showing results on the bundled sample_candidates.json for demo purposes.")
    lines = sample_path.read_text().splitlines()
elif uploaded is not None:
    raw = uploaded.read().decode("utf-8")
    lines = [l for l in raw.splitlines() if l.strip()]
else:
    lines = []

if lines:
    results = []
    n_honeypot = 0
    for line in lines:
        try:
            c = json.loads(line)
        except json.JSONDecodeError:
            continue
        feat = extract_features(c)
        if feat["is_honeypot"]:
            n_honeypot += 1
            continue
        sc = compute_score(feat)
        reasoning = build_reasoning(feat, sc)
        results.append({
            "candidate_id": feat["candidate_id"],
            "score": sc["final_score"],
            "title": feat["title"],
            "years_of_experience": feat["years_of_experience"],
            "reasoning": reasoning,
        })

    results.sort(key=lambda r: (-r["score"], r["candidate_id"]))
    for i, r in enumerate(results, start=1):
        r["rank"] = i

    df = pd.DataFrame(results)[["rank", "candidate_id", "score", "title", "years_of_experience", "reasoning"]]
    st.write(f"Ranked {len(df)} candidates ({n_honeypot} honeypots excluded).")
    st.dataframe(df, use_container_width=True, height=600)

    csv_buf = io.StringIO()
    df[["candidate_id", "rank", "score", "reasoning"]].to_csv(csv_buf, index=False)
    st.download_button("Download ranked CSV", csv_buf.getvalue(), file_name="submission_sample.csv")
else:
    st.warning("No candidate data loaded — upload a .jsonl file to begin.")

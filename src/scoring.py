"""
Hybrid scoring engine.

Design principles (per the challenge's own JD, read literally):
  - Title is a GATE, not just a feature. A Marketing Manager with 9 AI skills
    listed does not get a high score no matter how good the skill-match number
    looks — this is the explicit anti-keyword-stuffing defense.
  - Missing sections never zero out a component; weights redistribute across
    whatever IS present (dynamic weight normalization), so freshers / thin
    profiles aren't unfairly tanked just because a section is empty.
  - Behavioral signals (Redrob) are a MULTIPLIER on top of content fit, not
    an additive score — a perfect-on-paper candidate who is unreachable
    (5% response rate, inactive 6 months) should not outrank a slightly
    weaker but reachable candidate. But a bad behavioral signal should not
    be able to fully erase a strong content match either (floor at 0.55x).
  - Honeypots are excluded outright (not just down-weighted) — this dataset
    was explicitly built to test whether the ranker is actually reading
    profiles.
"""
from __future__ import annotations
import math
from datetime import date

from jd_config import (
    MANDATORY_SKILL_GROUPS, PREFERRED_SKILLS, AI_BUZZWORD_SKILLS,
    EXPERIENCE_SWEET_SPOT, EXPERIENCE_ACCEPTABLE, PREFERRED_LOCATIONS_TIER1,
    PREFERRED_LOCATIONS_TIER2, COUNTRY_REQUIRED, NOTICE_PERIOD_GOOD_DAYS,
    BASE_WEIGHTS, BEHAVIORAL_MULTIPLIER_WEIGHT,
)

TODAY = date(2026, 6, 1)


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
# Component scorers — each returns (score in [0,1], available: bool)
# `available=False` means "this candidate has no signal for this component
# at all" (not "signal is 0") so the aggregator can renormalize weights.
# ---------------------------------------------------------------------------

def score_title(feat: dict) -> tuple[float, bool]:
    cls = feat["title_class"]
    return {"core": 1.0, "adjacent": 0.55, "unknown": 0.35, "irrelevant": 0.05}[cls], True


def score_skills(feat: dict, embed_sim: float | None = None) -> tuple[float, bool]:
    skills = [_norm(s) for s in feat["skill_names"]]
    if not skills:
        return 0.0, False

    # mandatory group coverage: fraction of the 4 groups satisfied by >=1 exact/substring hit
    groups_hit = 0
    for group_terms in MANDATORY_SKILL_GROUPS.values():
        if any(any(term in sk or sk in term for term in group_terms) for sk in skills):
            groups_hit += 1
    mandatory_coverage = groups_hit / len(MANDATORY_SKILL_GROUPS)

    preferred_hits = sum(1 for sk in skills if any(p in sk for p in PREFERRED_SKILLS))
    preferred_score = _clip01(preferred_hits / 4)

    exact_score = 0.75 * mandatory_coverage + 0.25 * preferred_score

    if embed_sim is not None:
        # blend exact term coverage with semantic similarity from precomputed
        # embeddings (see embeddings.py) — semantic catches "Elasticsearch" vs
        # "OpenSearch" style synonyms that substring matching misses.
        return _clip01(0.6 * exact_score + 0.4 * embed_sim), True
    return exact_score, True


def score_buzzword_penalty(feat: dict) -> float:
    """Returns a MULTIPLIER (not additive) applied only when title is irrelevant
    but skills are buzzword-heavy — the keyword-stuffer signature."""
    skills = [_norm(s) for s in feat["skill_names"]]
    buzzword_hits = sum(1 for b in AI_BUZZWORD_SKILLS if any(b in sk for sk in skills))
    if feat["title_class"] == "irrelevant" and buzzword_hits >= 4:
        return 0.35  # heavy penalty multiplier, not full zero (JD says "no matter how perfect" — but we keep a floor for defensibility)
    return 1.0


def score_career_evidence(feat: dict) -> tuple[float, bool]:
    """Looks for the JD's actual asks: production deployment, ranking/search/
    recommendation systems shipped, product company (vs. pure IT-services/
    consulting), NLP/IR relevance."""
    career = feat["career_history"]
    if not career:
        return 0.0, False

    text_blob = " ".join(
        [feat.get("summary", ""), feat.get("headline", "")]
        + [ch.get("description", "") for ch in career]
        + [ch.get("title", "") for ch in career]
    ).lower()

    signal_terms = [
        "ranking", "search", "retrieval", "recommend", "recommendation",
        "embedding", "vector", "relevance", "nlp", "information retrieval",
        "ml pipeline", "production", "scale", "real-time", "real time",
    ]
    hits = sum(1 for t in signal_terms if t in text_blob)
    shipped_score = _clip01(hits / 6)

    # product company vs IT-services proxy: IT Services industry tag on most roles
    industries = [_norm(ch.get("industry", "")) for ch in career]
    it_services_frac = (
        sum(1 for i in industries if "it services" in i) / len(industries) if industries else 0
    )
    product_company_bonus = 1.0 - 0.4 * it_services_frac  # soft penalty, not disqualifying alone

    score = _clip01(shipped_score * product_company_bonus)
    return score, True


def score_experience_band(feat: dict) -> tuple[float, bool]:
    yoe = feat.get("years_of_experience")
    if yoe is None:
        return 0.0, False
    lo, hi = EXPERIENCE_SWEET_SPOT
    alo, ahi = EXPERIENCE_ACCEPTABLE
    if lo <= yoe <= hi:
        return 1.0, True
    if alo <= yoe < lo:
        return _clip01(0.5 + 0.5 * (yoe - alo) / (lo - alo)), True
    if hi < yoe <= ahi:
        return _clip01(1.0 - 0.5 * (yoe - hi) / (ahi - hi)), True
    return 0.15, True  # far outside band — not zero, could still have exceptional signals elsewhere


def score_location(feat: dict) -> tuple[float, bool]:
    loc = _norm(feat.get("location", ""))
    country = _norm(feat.get("country", ""))
    if not loc:
        return 0.0, False
    if any(t in loc for t in PREFERRED_LOCATIONS_TIER1):
        return 1.0, True
    if any(t in loc for t in PREFERRED_LOCATIONS_TIER2):
        return 0.8, True
    if country == COUNTRY_REQUIRED:
        return 0.55, True
    return 0.25, True  # outside India — JD says case-by-case, no visa sponsorship


def score_education(feat: dict) -> tuple[float, bool]:
    edu = feat.get("education", [])
    if not edu:
        return 0.0, False
    tier_map = {"tier_1": 1.0, "tier_2": 0.8, "tier_3": 0.6, "tier_4": 0.45, "unknown": 0.5}
    best = max((tier_map.get(e.get("tier", "unknown"), 0.5) for e in edu), default=0.5)
    return best, True


def score_disqualifiers(feat: dict) -> float:
    """Returns a penalty to SUBTRACT (0 to |BASE_WEIGHTS['disqualifier_penalty']|)."""
    flags = feat["disqualifier_flags"]
    weight = abs(BASE_WEIGHTS["disqualifier_penalty"])
    if not flags:
        return 0.0
    # Each flag contributes; capped at full weight.
    per_flag = weight / 2.0
    penalty = min(weight, per_flag * len(flags))
    return penalty


def score_behavioral(feat: dict) -> tuple[float, bool]:
    parts = []
    if feat.get("recruiter_response_rate") is not None:
        parts.append(feat["recruiter_response_rate"])
    if feat.get("days_inactive") is not None:
        # recent activity -> 1.0 within 30d, decays to 0 by 180d+
        di = feat["days_inactive"]
        parts.append(_clip01(1.0 - di / 180.0))
    if feat.get("interview_completion_rate") is not None:
        parts.append(feat["interview_completion_rate"])
    if feat.get("open_to_work_flag") is not None:
        parts.append(1.0 if feat["open_to_work_flag"] else 0.3)
    if feat.get("notice_period_days") is not None:
        np_days = feat["notice_period_days"]
        parts.append(1.0 if np_days <= NOTICE_PERIOD_GOOD_DAYS else _clip01(1.0 - (np_days - 30) / 150.0))
    if feat.get("profile_completeness_score") is not None:
        parts.append(feat["profile_completeness_score"] / 100.0)

    if not parts:
        return 0.5, False  # neutral default, no data
    return _clip01(sum(parts) / len(parts)), True


# ---------------------------------------------------------------------------
# Aggregator with dynamic weight normalization
# ---------------------------------------------------------------------------

def compute_score(feat: dict, embed_sim: float | None = None) -> dict:
    components = {
        "title_fit": score_title(feat),
        "skill_match": score_skills(feat, embed_sim=embed_sim),
        "career_evidence": score_career_evidence(feat),
        "experience_band": score_experience_band(feat),
        "location": score_location(feat),
        "education": score_education(feat),
    }

    available_weight_sum = sum(
        BASE_WEIGHTS[name] for name, (_, avail) in components.items() if avail
    )
    if available_weight_sum <= 0:
        content_score = 0.0
    else:
        content_score = sum(
            (BASE_WEIGHTS[name] / available_weight_sum) * val
            for name, (val, avail) in components.items() if avail
        )

    # keyword-stuffer multiplier (title-gate reinforcement)
    content_score *= score_buzzword_penalty(feat)

    # disqualifier penalty (subtractive, from JD's explicit "do not want" list)
    content_score = _clip01(content_score - score_disqualifiers(feat))

    behavior_score, behavior_avail = score_behavioral(feat)
    w = BEHAVIORAL_MULTIPLIER_WEIGHT if behavior_avail else 0.0
    # behavioral acts mostly as a multiplier with a floor, so it can't zero out a strong match
    behavior_multiplier = 0.55 + 0.45 * behavior_score
    final = content_score * (1 - w) + (content_score * behavior_multiplier) * w

    if feat["is_honeypot"]:
        final = 0.0  # hard exclude — dataset is explicitly designed to test this

    return {
        "final_score": round(_clip01(final), 4),
        "content_score": round(content_score, 4),
        "behavior_score": round(behavior_score, 4),
        "components": {k: round(v[0], 3) for k, v in components.items()},
        "disqualifier_flags": list(feat["disqualifier_flags"].keys()),
        "is_honeypot": feat["is_honeypot"],
    }

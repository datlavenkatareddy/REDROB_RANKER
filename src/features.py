"""
Turn a raw candidate record (per candidate_schema.json) into:
  1. a flat feature dict used by the scorer
  2. a honeypot/trap flag with reasons (internal-consistency checks only —
     we don't have an external company-founding-date database, so we check
     what's actually checkable from the profile itself)

Design note on missing sections (dynamic weight normalization): every
extractor here returns None for "not present" rather than 0, so the scorer
can tell the difference between "candidate has 0 GitHub activity" and
"candidate didn't link GitHub" and renormalize weights accordingly instead
of unfairly zeroing a fresher/incomplete profile.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Any

from jd_config import (
    CORE_FIT_TITLES, ADJACENT_TITLES, IRRELEVANT_TITLES, CONSULTING_FIRMS,
    RESEARCH_ONLY_INDUSTRY_HINTS, TITLE_CHASER_LADDER, AI_BUZZWORD_SKILLS,
)

TODAY = date(2026, 6, 1)  # dataset generation reference point (stable, not wall-clock)


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _norm(s: str) -> str:
    return (s or "").strip().lower()


# ---------------------------------------------------------------------------
# Honeypot / trap detection — internal consistency only.
# ---------------------------------------------------------------------------

def detect_honeypot(c: dict) -> tuple[bool, list[str]]:
    """
    Calibrated against the actual released dataset (100K candidates), not
    guessed blind. Two independent patterns were confirmed present in the
    real data with zero false-positive noise on normal profiles:

      (a) 3+ skills marked "expert" with duration_months == 0 — directly
          matches the hackathon doc's own honeypot example ("'expert'
          proficiency in 10 skills with 0 years used").
      (b) career_history durations, summed, exceed the profile's stated
          years_of_experience by a wide margin — i.e. more time worked than
          the candidate claims to have. (The reverse — history summing to
          LESS than stated experience — is normal: career_history is
          schema-capped at 10 entries, so veterans' older roles are
          legitimately omitted. Only over-count is a real contradiction.)

    Other candidate axes checked and found clean in the real data (i.e. NOT
    used as honeypot signals here, because the generator keeps them
    consistent for everyone): duration_months vs. actual date-span, and
    profile.current_title/current_company vs. the is_current career_history
    entry. Flagging on those would produce false positives, not catch traps.
    """
    reasons = []

    # (a) multiple expert-level skills claimed with zero months of use
    zero_dur_expert = [
        s for s in c.get("skills", [])
        if _norm(s.get("proficiency")) == "expert" and (s.get("duration_months") or 0) == 0
    ]
    if len(zero_dur_expert) >= 3:
        names = [s.get("name") for s in zero_dur_expert]
        reasons.append(f"{len(zero_dur_expert)} skills at 'expert' with 0 months used: {names}")

    # (b) career_history total time worked exceeds claimed total experience
    yoe = c.get("profile", {}).get("years_of_experience")
    total_months = sum((ch.get("duration_months") or 0) for ch in c.get("career_history", []))
    if yoe is not None and total_months > 0:
        implied_years = total_months / 12.0
        if implied_years > yoe * 1.15 and (implied_years - yoe) > 1.0:
            reasons.append(
                f"career_history implies {implied_years:.1f} yrs worked, "
                f"exceeding stated years_of_experience={yoe}"
            )

    # 4. Overlapping "is_current" roles (more than one current job).
    current_roles = [ch for ch in c.get("career_history", []) if ch.get("is_current")]
    if len(current_roles) > 1:
        reasons.append(f"{len(current_roles)} career_history entries marked is_current")

    # 5. is_current=True but end_date is set (or vice versa: not current but no end_date).
    for ch in c.get("career_history", []):
        if ch.get("is_current") and ch.get("end_date"):
            reasons.append("is_current=true but end_date is set")
            break
    for ch in c.get("career_history", []):
        if not ch.get("is_current") and not ch.get("end_date"):
            reasons.append("role marked not-current but has no end_date")
            break

    # 6. Overlapping employment date ranges (two full-time jobs at once, unexplained).
    spans = []
    for ch in c.get("career_history", []):
        sd = _parse_date(ch.get("start_date"))
        ed = _parse_date(ch.get("end_date")) or TODAY
        if sd:
            spans.append((sd, ed))
    spans.sort()
    for i in range(len(spans) - 1):
        if spans[i][1] > spans[i + 1][0]:
            overlap_days = (spans[i][1] - spans[i + 1][0]).days
            if overlap_days > 45:  # small overlap = normal transition noise
                reasons.append(f"overlapping employment spans by {overlap_days} days")
                break

    # 7. skill_assessment_scores reference skills nowhere in the skills list, at
    #    implausibly high scores (fabricated assessment signal).
    skill_names = {_norm(s.get("name")) for s in c.get("skills", [])}
    sas = c.get("redrob_signals", {}).get("skill_assessment_scores", {}) or {}
    ghost_high_scores = [
        k for k, v in sas.items() if _norm(k) not in skill_names and v is not None and v >= 90
    ]
    if len(ghost_high_scores) >= 2:
        reasons.append(f"high assessment scores for skills not listed: {ghost_high_scores}")

    # Primary signals (a) and (b) are individually reliable (data-confirmed,
    # zero false positives observed). Auxiliary signals below (overlapping
    # current roles, ghost assessment scores) are weaker on their own, so
    # require a primary signal OR 2+ auxiliary signals together.
    primary_hits = sum(1 for r in reasons if "expert" in r or "career_history implies" in r)
    is_honeypot = primary_hits >= 1 or len(reasons) >= 2
    return (is_honeypot, reasons)


# ---------------------------------------------------------------------------
# Title classification
# ---------------------------------------------------------------------------

def classify_title(title: str) -> str:
    t = _norm(title)
    if any(k in t for k in CORE_FIT_TITLES):
        return "core"
    if any(k in t for k in ADJACENT_TITLES):
        return "adjacent"
    if any(k in t for k in IRRELEVANT_TITLES):
        return "irrelevant"
    return "unknown"


# ---------------------------------------------------------------------------
# Disqualifier / soft-penalty signals from the JD's explicit "do not want" list
# ---------------------------------------------------------------------------

def compute_disqualifier_flags(c: dict) -> dict:
    flags = {}
    profile = c.get("profile", {})
    career = c.get("career_history", [])

    # Consulting-only career (all employers are consulting firms).
    companies = [_norm(ch.get("company")) for ch in career] + [_norm(profile.get("current_company"))]
    if companies and all(any(cf in comp for cf in CONSULTING_FIRMS) for comp in companies if comp):
        flags["consulting_only"] = True

    # Pure research background: industry consistently research/academia, no
    # product-company signal anywhere in career history.
    industries = [_norm(ch.get("industry")) for ch in career] + [_norm(profile.get("current_industry"))]
    if industries and all(
        any(h in ind for h in RESEARCH_ONLY_INDUSTRY_HINTS) for ind in industries if ind
    ):
        flags["research_only"] = True

    # Title-chaser: senior-ladder title escalating with short tenures (<18mo avg)
    # across 3+ employers.
    ladder_hits = sum(
        1 for ch in career if any(w in _norm(ch.get("title")) for w in TITLE_CHASER_LADDER)
    )
    short_tenures = [ch for ch in career if (ch.get("duration_months") or 999) < 18]
    if ladder_hits >= 2 and len(short_tenures) >= 2 and len(career) >= 3:
        flags["title_chaser"] = True

    # Senior title but hasn't written production code recently: current title
    # suggests pure management/architecture AND current role duration > 18mo
    # with a managerial-sounding title and no IC signal in description.
    cur_title = _norm(profile.get("current_title"))
    if any(w in cur_title for w in ["architect", "tech lead", "engineering manager", "director", "vp", "head of"]):
        flags["possible_non_ic"] = True

    # AI experience is recent-only (<12mo tenure at current role) AND skills are
    # dominated by buzzwords with no earlier ML/data-adjacent role in history.
    cur_role_months = None
    for ch in career:
        if ch.get("is_current"):
            cur_role_months = ch.get("duration_months")
            break
    skill_names = [_norm(s.get("name")) for s in c.get("skills", [])]
    buzzword_hits = sum(1 for b in AI_BUZZWORD_SKILLS if b in skill_names)
    has_earlier_ml_role = any(
        classify_title(ch.get("title", "")) == "core" for ch in career if not ch.get("is_current")
    )
    if (
        cur_role_months is not None and cur_role_months < 12
        and buzzword_hits >= 4
        and not has_earlier_ml_role
        and classify_title(cur_title) != "core"
    ):
        flags["recent_buzzword_only"] = True

    return flags


# ---------------------------------------------------------------------------
# Full feature extraction
# ---------------------------------------------------------------------------

def extract_features(c: dict) -> dict:
    profile = c.get("profile", {})
    signals = c.get("redrob_signals", {})
    is_honeypot, honeypot_reasons = detect_honeypot(c)

    last_active = _parse_date(signals.get("last_active_date"))
    days_inactive = (TODAY - last_active).days if last_active else None

    skills = c.get("skills", [])
    skill_names = [s.get("name", "") for s in skills]

    feat = {
        "candidate_id": c["candidate_id"],
        "title": profile.get("current_title", ""),
        "title_class": classify_title(profile.get("current_title", "")),
        "company": profile.get("current_company", ""),
        "years_of_experience": profile.get("years_of_experience"),
        "location": profile.get("location", ""),
        "country": profile.get("country", ""),
        "industry": profile.get("current_industry", ""),
        "headline": profile.get("headline", ""),
        "summary": profile.get("summary", ""),
        "skill_names": skill_names,
        "career_history": c.get("career_history", []),
        "education": c.get("education", []),
        "is_honeypot": is_honeypot,
        "honeypot_reasons": honeypot_reasons,
        "disqualifier_flags": compute_disqualifier_flags(c),
        # behavioral (may be None -> handled by dynamic weighting)
        "recruiter_response_rate": signals.get("recruiter_response_rate"),
        "open_to_work_flag": signals.get("open_to_work_flag"),
        "days_inactive": days_inactive,
        "interview_completion_rate": signals.get("interview_completion_rate"),
        "notice_period_days": signals.get("notice_period_days"),
        "profile_completeness_score": signals.get("profile_completeness_score"),
        "github_activity_score": signals.get("github_activity_score"),
        "verified_email": signals.get("verified_email"),
        "verified_phone": signals.get("verified_phone"),
        "saved_by_recruiters_30d": signals.get("saved_by_recruiters_30d"),
    }
    return feat

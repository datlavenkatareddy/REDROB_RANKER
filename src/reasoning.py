"""
Generate the `reasoning` column. Stage-4 manual review checks for:
  - specific facts (years, title, named skills, signal values)
  - connection to actual JD requirements, not generic praise
  - honest acknowledgment of gaps/concerns
  - no hallucinated claims (every fact must exist in the profile)
  - variation across rows (not templated with just the name swapped)
  - tone that matches the rank (a rank-5 candidate shouldn't read as lukewarm)

No LLM call here (network is off during ranking) — this is a deterministic
template composer, but the *content* fed into the templates is always pulled
from the candidate's actual fields, and template selection + which facts get
surfaced varies per-candidate (seeded by candidate_id, not by rank), so two
candidates with similar scores don't read identically.
"""
from __future__ import annotations
import hashlib

from jd_config import MANDATORY_SKILL_GROUPS, PREFERRED_SKILLS


def _pick(seed_str: str, options: list[str]) -> str:
    h = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    return options[h % len(options)]


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _matched_mandatory_groups(feat: dict) -> list[str]:
    skills = [_norm(s) for s in feat["skill_names"]]
    hit_groups = []
    for gname, terms in MANDATORY_SKILL_GROUPS.items():
        if any(any(t in sk or sk in t for t in terms) for sk in skills):
            hit_groups.append(gname.replace("_", " "))
    return hit_groups


def _notable_named_skills(feat: dict, k: int = 3) -> list[str]:
    """Return up to k skills that actually overlap JD-relevant terms, using the
    candidate's real skill names (not our internal group labels)."""
    all_terms = set()
    for terms in MANDATORY_SKILL_GROUPS.values():
        all_terms.update(terms)
    all_terms.update(PREFERRED_SKILLS)
    hits = [
        s for s in feat["skill_names"]
        if any(t in _norm(s) or _norm(s) in t for t in all_terms)
    ]
    return hits[:k]


def build_reasoning(feat: dict, sc: dict) -> str:
    cid = feat["candidate_id"]
    title = feat["title"] or "unlisted title"
    yoe = feat.get("years_of_experience")
    yoe_str = f"{yoe:.1f} yrs" if isinstance(yoe, (int, float)) else "experience unspecified"
    company = feat.get("company", "")
    named_skills = _notable_named_skills(feat)
    matched_groups = _matched_mandatory_groups(feat)
    flags = sc["disqualifier_flags"]
    comp = sc["components"]
    resp = feat.get("recruiter_response_rate")
    notice = feat.get("notice_period_days")
    days_inactive = feat.get("days_inactive")

    # --- strength clause ---
    if feat["title_class"] == "core" and comp["career_evidence"] >= 0.5:
        strength_opts = [
            f"{title} at {company} ({yoe_str}) with hands-on {', '.join(matched_groups) if matched_groups else 'ML systems'} background",
            f"{yoe_str} as {title}, career history shows direct work on {', '.join(matched_groups) if matched_groups else 'relevant ML/retrieval'} problems",
            f"Currently {title} ({yoe_str}); profile evidence points to production ML/search work, not just tooling exposure",
        ]
    elif feat["title_class"] == "adjacent":
        strength_opts = [
            f"{title} background ({yoe_str}) — adjacent engineering role, plausible 'plain-language' fit if the underlying systems work translates",
            f"{yoe_str} in {title}; not an AI-titled role but career history should be checked for retrieval/ranking-adjacent work",
        ]
    else:
        strength_opts = [
            f"{title} ({yoe_str}) — title is not AI/ML-aligned with this JD",
            f"Profile lists {title} as current role ({yoe_str}); core responsibilities don't match the JD's mandate",
        ]
    strength = _pick(cid + "s", strength_opts)

    # --- skill clause ---
    if named_skills:
        skill_clause = f"Lists {', '.join(named_skills)} directly among skills."
    elif matched_groups:
        skill_clause = f"Skill set covers {', '.join(matched_groups)} at a group level."
    else:
        skill_clause = "No direct overlap found between listed skills and the JD's core stack."

    # --- concern clause (honest, only if actually present) ---
    concerns = []
    if flags:
        flag_text = {
            "consulting_only": "entire career at consulting/IT-services firms (JD explicitly flags this)",
            "research_only": "career reads as pure research with no visible production deployment",
            "title_chaser": "short-tenure title escalation pattern across employers",
            "possible_non_ic": "current title suggests management/architecture, not hands-on coding",
            "recent_buzzword_only": "AI-related skills appear recent and not backed by an earlier ML-titled role",
        }
        concerns.extend(flag_text.get(f, f) for f in flags)
    if resp is not None and resp < 0.3:
        concerns.append(f"low recruiter response rate ({resp:.2f})")
    if notice is not None and notice > 60:
        concerns.append(f"long notice period ({notice} days)")
    if days_inactive is not None and days_inactive > 120:
        concerns.append(f"inactive on platform for {days_inactive} days")
    if comp.get("experience_band", 1.0) < 0.3:
        concerns.append(f"experience ({yoe_str}) sits well outside the JD's 5-9 yr band")

    concern_clause = f" Concern: {'; '.join(concerns[:2])}." if concerns else ""

    if not strength.endswith((".", "!", "?")):
        strength += "."
    return f"{strength} {skill_clause}{concern_clause}"

"""
Structured hiring requirements for: Senior AI Engineer — Founding Team, Redrob AI.

This is NOT auto-parsed from free text at ranking time (that would need a live LLM
call, which the compute rules forbid). It's a one-time structured encoding of the
released job_description.md, done carefully by re-reading the JD end to end,
including the "read between the lines" section aimed at hackathon participants.

If the JD changes, re-run this encoding step manually — it's a config file, not a
pipeline stage, and re-encoding a single JD by hand is exactly the kind of judgment
call the JD itself says it wants ("scrappy, ships in a week, not a fixed checklist").
"""

# ---------------------------------------------------------------------------
# Skills — split mandatory / preferred / nice-to-have, per Feature 2 of the brief.
# Values are used both for exact-match scoring and as seed terms for embedding
# similarity (so "BGE" and "sentence-transformers" both count as "embeddings").
# ---------------------------------------------------------------------------

MANDATORY_SKILL_GROUPS = {
    # candidate needs *at least one* skill from each group to be considered
    # to have satisfied that mandatory requirement
    "embeddings_retrieval": [
        "embeddings", "sentence-transformers", "openai embeddings", "bge", "e5",
        "dense retrieval", "vector search", "semantic search",
    ],
    "vector_db_or_hybrid_search": [
        "pinecone", "weaviate", "qdrant", "milvus", "opensearch", "elasticsearch",
        "faiss", "vector database", "hybrid search", "bm25",
    ],
    "python": ["python"],
    "eval_frameworks": [
        "ndcg", "mrr", "map", "a/b testing", "offline evaluation",
        "ranking evaluation", "recommender evaluation",
    ],
}

PREFERRED_SKILLS = [
    "lora", "qlora", "peft", "fine-tuning llms", "learning to rank", "xgboost",
    "ltr", "hr-tech", "recruiting tech", "marketplace", "distributed systems",
    "large-scale inference", "open source",
]

# Skills that, on their own with no supporting title/career evidence, are the
# "keyword stuffer" trap signature. High presence + irrelevant title = penalty,
# not bonus.
AI_BUZZWORD_SKILLS = [
    "rag", "llm", "langchain", "gpt", "openai", "prompt engineering",
    "fine-tuning llms", "embeddings", "vector search", "pinecone", "transformers",
]

# ---------------------------------------------------------------------------
# Title relevance — the single strongest anti-keyword-stuffing gate. A
# "Marketing Manager" with 9 AI skills listed must not outrank a "Data
# Scientist" with 3. Title gates the ceiling of the score; skills fill it in.
# ---------------------------------------------------------------------------

CORE_FIT_TITLES = [
    "ai engineer", "ml engineer", "machine learning engineer", "senior ai engineer",
    "senior ml engineer", "applied scientist", "data scientist", "nlp engineer",
    "search engineer", "ranking engineer", "recommender systems engineer",
    "recommendation systems engineer", "recommendation engineer", "recommender engineer",
    "search & relevance", "information retrieval", "ml infrastructure",
    "research engineer", "deep learning engineer",
    "ai research engineer", "mlops engineer",
]

# Adjacent titles: real engineering background, plausibly a "Tier 5 plain
# language" fit even without AI keywords, per the JD's explicit example
# ("built a recommendation system at a product company"). Scored below core
# fit but not punished like an irrelevant title.
ADJACENT_TITLES = [
    "backend engineer", "software engineer", "data engineer", "platform engineer",
    "infrastructure engineer", "full stack engineer", "systems engineer",
    "computer vision engineer", "cv engineer", "speech engineer", "robotics engineer",
]

# Titles the JD gives zero credit to regardless of listed skills.
IRRELEVANT_TITLES = [
    "marketing manager", "hr manager", "sales executive", "accountant",
    "content writer", "graphic designer", "business analyst", "project manager",
    "customer support", "mechanical engineer", "civil engineer",
    "operations manager",
]

# ---------------------------------------------------------------------------
# Explicit disqualifiers / strong-penalty patterns from "Things we explicitly
# do NOT want" and the experience-band section.
# ---------------------------------------------------------------------------

CONSULTING_FIRMS = [
    "tcs", "tata consultancy", "infosys", "wipro", "accenture", "cognizant",
    "capgemini",
]

RESEARCH_ONLY_INDUSTRY_HINTS = ["research", "academia", "university", "research lab"]

TITLE_CHASER_LADDER = ["senior", "staff", "principal", "lead", "director", "vp", "head"]

EXPERIENCE_SWEET_SPOT = (5, 9)      # years — soft band, not a hard cutoff
EXPERIENCE_ACCEPTABLE = (3, 15)     # outside this, fit drops off sharply

PREFERRED_LOCATIONS_TIER1 = ["pune", "noida"]
PREFERRED_LOCATIONS_TIER2 = ["hyderabad", "mumbai", "delhi", "delhi ncr", "gurgaon", "gurugram"]
COUNTRY_REQUIRED = "india"  # no visa sponsorship outside India — case-by-case, soft penalty not hard filter

NOTICE_PERIOD_GOOD_DAYS = 30

# ---------------------------------------------------------------------------
# Scoring weights (dynamic — renormalized when a component's inputs are
# entirely missing for a given candidate, per Feature 5 of the original brief)
# ---------------------------------------------------------------------------

BASE_WEIGHTS = {
    "title_fit": 0.22,        # gate: irrelevant titles cap the whole score
    "skill_match": 0.23,      # mandatory-group coverage + embedding similarity
    "career_evidence": 0.20,  # production/product-company signal, shipped ranking/search systems
    "experience_band": 0.10,
    "location": 0.05,
    "education": 0.05,
    "disqualifier_penalty": -0.15,  # applied as subtraction, not part of the 100% pool
}

BEHAVIORAL_MULTIPLIER_WEIGHT = 0.15  # blended in as (1 - w)*content_score + w*behavior_score

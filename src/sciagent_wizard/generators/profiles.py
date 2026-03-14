"""
Build profiles — compile-time agent/skill consolidation for wizard output.

Mirrors the profile system in ``sciagent/scripts/build_plugin.py`` so
that wizard-generated projects use the same streamlined structure.

Each profile defines:
    exclude_agents  — agent stems to omit entirely
    exclude_skills  — skill directory names to omit entirely
    merge_agents    — merged-agent-name → merge spec
    merge_skills    — merged-skill-name → merge spec
    handoff_rewrites — rewrite ``agent: <old>`` refs; None = remove handoff
    body_rewrites   — plain-text replacements applied to agent body content
"""

from __future__ import annotations

from typing import Any


# ── Profile definitions ─────────────────────────────────────────────────

PROFILES: dict[str, dict[str, Any]] = {
    "full": {
        "exclude_agents": [],
        "exclude_skills": [],
        "merge_agents": {},
        "merge_skills": {},
        "handoff_rewrites": {},
        "body_rewrites": {},
    },
    "compact": {
        "exclude_agents": ["analysis-planner", "data-qc"],
        "exclude_skills": ["update-domain"],
        "merge_agents": {
            "reviewer": {
                "sources": ["code-reviewer", "rigor-reviewer"],
                "description": (
                    "Reviews analysis code and results for correctness, "
                    "reproducibility, scientific validity, and rigor — "
                    "combining code review with scientific audit in one pass."
                ),
                "argument_hint": "Provide code or analysis results to review.",
                "tools": ["vscode", "vscode/askQuestions", "read", "search", "web/fetch"],
                "handoffs": [
                    {
                        "label": "Implement Fixes",
                        "agent": "coder",
                        "prompt": "Implement the changes recommended in the review above.",
                        "send": True,
                    },
                    {
                        "label": "Generate Report",
                        "agent": "report-writer",
                        "prompt": "Generate a structured report from the reviewed analysis.",
                        "send": False,
                    },
                ],
            },
        },
        "merge_skills": {
            "review": {
                "sources": ["code-reviewer", "rigor-reviewer"],
                "description": (
                    "Reviews analysis code and results for correctness, "
                    "reproducibility, scientific validity, and rigor — "
                    "combining code review with scientific audit in one pass."
                ),
                "section_titles": {
                    "code-reviewer": "Code Quality Review",
                    "rigor-reviewer": "Scientific Rigor Audit",
                },
            },
            "configure-domain": {
                "sources": ["configure-domain", "update-domain"],
                "description": None,  # keep original description from first source
                "section_titles": {
                    "configure-domain": None,  # keep as-is, no extra header
                    "update-domain": "Incremental Update Mode",
                },
            },
        },
        "handoff_rewrites": {
            "code-reviewer": "reviewer",
            "rigor-reviewer": "reviewer",
            "analysis-planner": None,
            "data-qc": None,
        },
        "body_rewrites": {
            "@analysis-planner": "the `/analysis-planner` skill",
            "@data-qc": "the `/data-qc` skill",
            "@code-reviewer": "@reviewer",
            "@rigor-reviewer": "@reviewer",
        },
    },
}

# Agent stems that only exist in the compact profile (via merge).
COMPACT_ONLY_AGENTS: set[str] = {"reviewer"}

# Prompt modules to append per agent — the merged ``reviewer`` gets the
# union of code-reviewer + rigor-reviewer prompts (which are identical).
REVIEWER_PROMPT_MODULES: list[str] = [
    "scientific_rigor.md",
    "communication_style.md",
    "clarification.md",
]

# Agent roster entries for the compact profile (used by markdown generator).
COMPACT_AGENT_ROSTER: list[tuple[str, str]] = [
    ("coordinator", "Master triage and routing"),
    ("coder", "Implement code with scientific rigor"),
    ("reviewer", "Review code and results for correctness and rigor"),
    ("report-writer", "Generate structured reports"),
    ("docs-ingestor", "Learn new library APIs"),
    ("domain-assembler", "Configure domain knowledge"),
]

# Full profile roster (original 9-agent layout, minus domain-assembler's
# duplicate in some contexts).
FULL_AGENT_ROSTER: list[tuple[str, str]] = [
    ("coordinator", "Master triage and routing"),
    ("analysis-planner", "Design the analysis roadmap"),
    ("data-qc", "Check data quality before analysis"),
    ("coder", "Implement code with scientific rigor"),
    ("rigor-reviewer", "Audit results for scientific rigour"),
    ("report-writer", "Generate structured reports"),
    ("code-reviewer", "Review scripts for correctness"),
    ("docs-ingestor", "Learn new library APIs"),
    ("domain-assembler", "Configure domain knowledge"),
]


# ── Helper functions ────────────────────────────────────────────────────


def get_profile(name: str) -> dict[str, Any]:
    """Return a profile dict by name, defaulting to ``"compact"``."""
    return PROFILES.get(name, PROFILES["compact"])


def consumed_agent_sources(profile: dict[str, Any]) -> set[str]:
    """Return the set of agent stems consumed (merged into another agent)."""
    consumed: set[str] = set()
    for spec in profile.get("merge_agents", {}).values():
        consumed.update(spec.get("sources", []))
    return consumed


def consumed_skill_sources(profile: dict[str, Any]) -> set[str]:
    """Return the set of skill names consumed (merged into another skill)."""
    consumed: set[str] = set()
    for merged_name, spec in profile.get("merge_skills", {}).items():
        for src in spec.get("sources", []):
            # The first source in a self-merge (e.g. configure-domain absorbing
            # update-domain) keeps its name — only additional sources are consumed.
            if src != merged_name:
                consumed.add(src)
    return consumed


def is_excluded_agent(stem: str, profile: dict[str, Any]) -> bool:
    """Return True if *stem* should be omitted from output."""
    if stem in profile.get("exclude_agents", []):
        return True
    if stem in consumed_agent_sources(profile):
        return True
    return False


def is_excluded_skill(name: str, profile: dict[str, Any]) -> bool:
    """Return True if skill *name* should be omitted from output."""
    if name in profile.get("exclude_skills", []):
        return True
    if name in consumed_skill_sources(profile):
        return True
    return False


def get_agent_roster(profile_name: str) -> list[tuple[str, str]]:
    """Return ``[(stem, role_description), …]`` for the given profile."""
    if profile_name == "compact":
        return list(COMPACT_AGENT_ROSTER)
    return list(FULL_AGENT_ROSTER)

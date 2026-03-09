"""
copilot_gen — Generate VS Code custom agent + Claude Code sub-agent configs.

Produces a directory with:

    .github/agents/<name>.agent.md      VS Code Copilot custom agent
    .claude/agents/<name>.md            Claude Code sub-agent
    .github/instructions/<name>.instructions.md   Shared instructions
    docs/                                Package documentation
    README.md

Or, in plugin mode:

    .github/plugin/plugin.json          VS Code plugin manifest
    agents/<name>.md                    Compiled agent(s) with inlined instructions
    skills/<name>/SKILL.md              Domain skills
    docs/                               Package documentation
    README.md
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from sciagent_wizard.models import WizardState
from .docs_gen import write_docs
from .prompt_gen import _build_expertise_text
from sciagent_wizard.rendering import (
    render_docs as render_doc_templates,
    render_docs_with_domain_links,
)

logger = logging.getLogger(__name__)


def generate_copilot_project(
    state: WizardState,
    output_dir: Optional[str | Path] = None,
) -> Path:
    """Generate a VS Code / Claude Code agent config project.

    Args:
        state: Populated ``WizardState``.
        output_dir: Parent directory. Defaults to CWD.

    Returns:
        Path to the generated project directory.
    """
    base = Path(output_dir) if output_dir else Path.cwd()
    slug = state.agent_name.replace(" ", "_").replace("-", "_")
    project_dir = base / slug
    project_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Generating copilot/claude agent config in %s", project_dir)

    # ── Shared domain expertise (instructions) ──────────────────────
    expertise = _build_expertise_text(state)
    docs_ref = _docs_reference(state)
    full_instructions = expertise
    if docs_ref:
        full_instructions += "\n\n" + docs_ref

    # ── .github/instructions/<name>.instructions.md ─────────────────
    instructions_dir = project_dir / ".github" / "instructions"
    instructions_dir.mkdir(parents=True, exist_ok=True)
    instructions_path = instructions_dir / f"{state.agent_name}.instructions.md"
    instructions_path.write_text(full_instructions, encoding="utf-8")

    # ── .github/agents/<name>.agent.md (VS Code format) ─────────────
    agents_dir = project_dir / ".github" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    vscode_path = agents_dir / f"{state.agent_name}.agent.md"
    vscode_path.write_text(
        _vscode_agent_md(state, full_instructions), encoding="utf-8"
    )

    # ── .claude/agents/<name>.md (Claude Code format) ───────────────
    claude_dir = project_dir / ".claude" / "agents"
    claude_dir.mkdir(parents=True, exist_ok=True)
    claude_path = claude_dir / f"{state.agent_name}.md"
    claude_path.write_text(
        _claude_agent_md(state, full_instructions), encoding="utf-8"
    )

    # ── Package docs ────────────────────────────────────────────────
    docs_dir = project_dir / "docs"
    render_docs_with_domain_links(state, docs_dir)
    if state.package_docs:
        write_docs(state, docs_dir)

    # ── README ──────────────────────────────────────────────────────
    readme_path = project_dir / "README.md"
    readme_path.write_text(_readme(state), encoding="utf-8")

    state.project_dir = str(project_dir)
    logger.info("Copilot/Claude agent config generated: %s", project_dir)
    return project_dir


# ── VS Code .agent.md ──────────────────────────────────────────────────

_RIGOR_GUARDRAIL_INSTRUCTIONS = """\
### Scientific Rigor — Shell / Terminal Policy

**NEVER** use the `terminal` tool to execute data analysis or computation code.
All analysis must go through the provided analysis tools (e.g. `execute_code`)
which enforce scientific rigor checks automatically.

The `terminal` tool may be used **only** for environment setup tasks such as
`pip install`, `git` commands, or opening files — and only after describing the
command to the user.

If a rigor warning is raised by `execute_code` (indicated by
`needs_confirmation: true` in the result), you **MUST**:
1. Present the warnings to the user verbatim.
2. Ask whether to proceed.
3. If confirmed, re-call `execute_code` with `confirmed: true`.
4. Never silently bypass or suppress rigor warnings.
"""


def _vscode_agent_md(state: WizardState, instructions: str) -> str:
    """Generate a VS Code custom agent file (.agent.md format)."""
    # Tools: map to VS Code built-in tool names
    tools = [
        "codebase",       # search/read workspace files
        "terminal",       # run commands (pip, python, etc.)
        "search",         # web search
        "fetch",          # fetch URLs
        "editFiles",      # create/edit files
        "findTestFiles",  # discover test files
    ]
    tools_yaml = "\n".join(f"  - {t}" for t in tools)

    # Handoffs: suggest a planning → implementation flow
    handoffs_yaml = ""
    if state.agent_name:
        handoffs_yaml = f"""handoffs:
  - label: "Plan Analysis"
    agent: {state.agent_name}-planner
    prompt: "Create an analysis plan for the data using the available domain packages."
    send: false
  - label: "Review Results"
    agent: {state.agent_name}-reviewer
    prompt: "Review the analysis results and check for any issues."
    send: false"""

    frontmatter = f"""---
description: >-
  {state.agent_description}
name: {state.agent_name}
tools:
{tools_yaml}
{handoffs_yaml}
---"""

    return f"{frontmatter}\n\n{instructions}\n\n{_RIGOR_GUARDRAIL_INSTRUCTIONS}\n"


# ── Claude Code sub-agent .md ──────────────────────────────────────────


def _claude_agent_md(state: WizardState, instructions: str) -> str:
    """Generate a Claude Code sub-agent file (.md with YAML frontmatter)."""
    tools = "Read, Write, Edit, Bash, Grep, Glob"

    frontmatter = f"""---
name: {state.agent_name}
description: >-
  {state.agent_description}
tools: {tools}
model: sonnet
---"""

    return f"{frontmatter}\n\n{instructions}\n\n{_RIGOR_GUARDRAIL_INSTRUCTIONS}\n\n"


# ── Helpers ─────────────────────────────────────────────────────────────


def _docs_reference(state: WizardState) -> str:
    """Build a section pointing the agent to the local docs."""
    if not state.package_docs:
        return ""
    lines = [
        "### Package Documentation",
        "",
        "Local reference documentation is available in the `docs/` directory "
        "for each installed library. Consult these docs when you need "
        "detailed API information or usage examples:",
        "",
    ]
    for name in sorted(state.package_docs.keys()):
        lines.append(f"- `docs/{name.lower().replace(' ', '_')}.md`")
    return "\n".join(lines)


def _readme(state: WizardState) -> str:
    """Generate a README for the copilot/claude agent project."""
    slug = state.agent_name
    pkgs = "\n".join(
        f"- **{p.name}**: {p.description[:80]}"
        for p in state.confirmed_packages
    )

    return f"""\
# {state.agent_display_name}

{state.agent_description}

> Auto-generated by the **sciagent self-assembly wizard**.

## Output Mode: Copilot / Claude Code Agent

This project contains agent configuration files for use with:

### VS Code GitHub Copilot

The custom agent is defined in `.github/agents/{slug}.agent.md`.

To use it:
1. Copy this project into your workspace
2. Open VS Code with GitHub Copilot enabled
3. Select **{state.agent_display_name}** from the Agents dropdown in chat

### Claude Code

The sub-agent is defined in `.claude/agents/{slug}.md`.

To use it:
1. Copy the `.claude/agents/` folder into your project
2. Run Claude Code — it will auto-detect the sub-agent
3. Ask Claude to use the **{state.agent_name}** agent

### Shared Instructions

Domain expertise and instructions are in:
`.github/instructions/{slug}.instructions.md`

### Package Documentation

Local docs for each domain package are in `docs/`.

## Domain Packages

{pkgs or "No additional packages configured."}
"""


# ═══════════════════════════════════════════════════════════════════════════
# Copilot Plugin generation — full plugin.json + agents/ + skills/ layout
# ═══════════════════════════════════════════════════════════════════════════


def generate_copilot_plugin(
    state: WizardState,
    output_dir: Optional[str | Path] = None,
) -> Path:
    """Generate a VS Code Copilot agent plugin project.

    Produces the plugin directory format that VS Code can discover via
    ``chat.plugins.paths``:

    - ``.github/plugin/plugin.json`` — plugin manifest
    - ``agents/<name>.md`` — one compiled agent with inlined domain expertise
    - ``skills/<name>/SKILL.md`` — domain-specific skills
    - ``docs/`` — package documentation
    - ``README.md``

    Args:
        state: Populated ``WizardState``.
        output_dir: Parent directory. Defaults to CWD.

    Returns:
        Path to the generated plugin directory.
    """
    base = Path(output_dir) if output_dir else Path.cwd()
    slug = state.agent_name.replace(" ", "_").replace("-", "_")
    project_dir = base / slug
    project_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Generating copilot plugin in %s", project_dir)

    # ── Domain expertise text ───────────────────────────────────────
    expertise = _build_expertise_text(state)
    docs_ref = _docs_reference(state)
    full_instructions = expertise
    if docs_ref:
        full_instructions += "\n\n" + docs_ref

    # ── Build the main agent ────────────────────────────────────────
    agent_names = [state.agent_name]
    agent_content = _plugin_agent_md(state, full_instructions)
    agent_path = project_dir / "agents" / f"{state.agent_name}.md"
    agent_path.parent.mkdir(parents=True, exist_ok=True)
    agent_path.write_text(agent_content, encoding="utf-8")

    # ── Build skills ────────────────────────────────────────────────
    skill_names = _build_plugin_skills(state, project_dir, full_instructions)

    # ── plugin.json ─────────────────────────────────────────────────
    _write_plugin_json(state, project_dir, agent_names, skill_names)

    # ── Package docs ────────────────────────────────────────────────
    docs_dir = project_dir / "docs"
    render_docs_with_domain_links(state, docs_dir)
    if state.package_docs:
        write_docs(state, docs_dir)

    # ── README ──────────────────────────────────────────────────────
    readme_path = project_dir / "README.md"
    readme_path.write_text(
        _plugin_readme(state, agent_names, skill_names), encoding="utf-8"
    )

    state.project_dir = str(project_dir)
    logger.info("Copilot plugin generated: %s", project_dir)
    return project_dir


# ── Plugin agent .md ───────────────────────────────────────────────────


def _plugin_agent_md(state: WizardState, instructions: str) -> str:
    """Generate a compiled plugin agent (agents/<name>.md) with inlined expertise."""
    tools = [
        "vscode",
        "vscode/askQuestions",
        "read",
        "editFiles",
        "terminal",
        "search",
        "web/fetch",
    ]
    tools_yaml = "\n".join(f"  - {t}" for t in tools)

    handoffs_yaml = ""
    if state.agent_name:
        handoffs_yaml = f"""handoffs:
  - label: "Plan Analysis"
    agent: {state.agent_name}-planner
    prompt: "Create an analysis plan for the data using the available domain packages."
    send: false
  - label: "Review Results"
    agent: {state.agent_name}-reviewer
    prompt: "Review the analysis results and check for any issues."
    send: false"""

    frontmatter = f"""---
name: {state.agent_name}
description: >-
  {state.agent_description}
argument-hint: Describe your research task and data.
tools:
{tools_yaml}
{handoffs_yaml}
---"""

    body = instructions + "\n\n" + _RIGOR_GUARDRAIL_INSTRUCTIONS + "\n\n"
    return f"{frontmatter}\n\n{body}\n"


# ── Plugin skills ──────────────────────────────────────────────────────


def _build_plugin_skills(
    state: WizardState,
    project_dir: Path,
    full_instructions: str,
) -> list[str]:
    """Generate SKILL.md files for the plugin.

    Creates:
    - ``scientific-rigor`` — always included, inlined rigor principles
    - ``domain-expertise`` — domain knowledge extracted from wizard state
    - One skill per confirmed package if package docs are available

    Returns list of skill directory names.
    """
    skills_dir = project_dir / "skills"
    skill_names: list[str] = []

    # ── scientific-rigor skill (always present) ─────────────────────
    rigor_skill = skills_dir / "scientific-rigor" / "SKILL.md"
    rigor_skill.parent.mkdir(parents=True, exist_ok=True)
    rigor_skill.write_text(_scientific_rigor_skill_md(), encoding="utf-8")
    skill_names.append("scientific-rigor")

    # ── domain-expertise skill ──────────────────────────────────────
    domain_skill = skills_dir / "domain-expertise" / "SKILL.md"
    domain_skill.parent.mkdir(parents=True, exist_ok=True)
    domain_skill.write_text(
        _domain_expertise_skill_md(state, full_instructions), encoding="utf-8"
    )
    skill_names.append("domain-expertise")

    # ── per-package skills (if docs available) ──────────────────────
    for pkg in state.confirmed_packages:
        doc_key = pkg.name
        doc_content = state.package_docs.get(doc_key, "")
        # Also check for _api variant from deep ingestion
        api_key = f"{pkg.name}_api"
        api_content = state.package_docs.get(api_key, "")
        combined = (doc_content + "\n\n" + api_content).strip()
        if not combined:
            continue

        pkg_slug = pkg.name.lower().replace(" ", "-").replace("_", "-")
        pkg_skill_dir = skills_dir / pkg_slug
        pkg_skill_dir.mkdir(parents=True, exist_ok=True)
        pkg_skill_path = pkg_skill_dir / "SKILL.md"
        pkg_skill_path.write_text(
            _package_skill_md(pkg.name, pkg.description, combined),
            encoding="utf-8",
        )
        skill_names.append(pkg_slug)

    return skill_names


def _scientific_rigor_skill_md() -> str:
    """Generate the scientific-rigor SKILL.md content."""
    return """\
---
name: scientific-rigor
description: >-
  Enforces scientific rigor principles during data analysis — data integrity,
  objective analysis, sanity checks, transparent reporting, uncertainty
  quantification, reproducibility, and safe code execution. Auto-loads when
  scientific analysis is detected.
user-invokable: false
---

# Scientific Rigor Principles

These principles **must** be followed during any scientific data analysis.
They are enforced automatically whenever Copilot detects scientific work.

## 1. Data Integrity

- NEVER generate synthetic, fake, or simulated data to fill gaps or pass tests.
- Use real experimental data ONLY — if data is missing or corrupted, report
  honestly.
- If asked to generate test data, explicitly refuse and explain why.

## 2. Objective Analysis

- NEVER adjust methods, parameters, or thresholds to confirm a hypothesis.
- Reveal what the data actually shows, not what anyone wants it to show.
- Report unexpected or negative findings — they are scientifically valuable.

## 3. Sanity Checks

- Always validate inputs before analysis (check for NaN, Inf, empty arrays).
- Flag values outside expected ranges for the domain.
- Verify units and scaling are correct.
- Question results that seem too perfect or too convenient.

## 4. Transparent Reporting

- Report ALL results, including inconvenient ones.
- Acknowledge when analysis is uncertain or inconclusive.
- Never hide failed samples, bad data, or contradictory results.

## 5. Uncertainty & Error

- Always report confidence intervals, SEM, or SD where applicable.
- State N for all measurements.
- Acknowledge limitations of the analysis methods.

## 6. Reproducibility

- All code must be deterministic and reproducible.
- Document exact parameters, thresholds, and methods used.
- Random seeds must be set and documented if any stochastic methods are used.

## 7. Shell / Terminal Policy

- **NEVER** use the terminal tool to execute data analysis or computation code.
- All analysis must go through the provided analysis tools which enforce
  scientific rigor checks automatically.
- The terminal tool may be used **only** for environment setup tasks such as
  `pip install`, `git` commands, or opening files — and only after describing
  the command to the user.

## 8. Rigor Warnings

- When analysis tools return warnings requiring confirmation, you **MUST**
  present the warnings to the user verbatim and ask for confirmation.
- NEVER silently bypass, suppress, or ignore rigor warnings.
- If the user confirms, re-call the analysis tool with `confirmed: true`.
"""


def _domain_expertise_skill_md(state: WizardState, instructions: str) -> str:
    """Generate a domain-expertise SKILL.md wrapping the wizard-generated expertise."""
    return f"""\
---
name: domain-expertise
description: >-
  Domain-specific expertise for {state.agent_display_name} — libraries,
  data formats, expected value ranges, and research context. Auto-loads
  alongside the main agent.
user-invokable: false
---

{instructions}
"""


def _package_skill_md(name: str, description: str, doc_content: str) -> str:
    """Generate a per-package SKILL.md with API reference and usage info."""
    slug = name.lower().replace(" ", "-").replace("_", "-")
    desc_line = description[:120] if description else f"Reference documentation for {name}."
    return f"""\
---
name: {slug}
description: >-
  {desc_line}
argument-hint: Ask about {name} APIs, usage patterns, or troubleshooting.
---

# {name} — Reference

{doc_content}
"""


# ── Plugin manifest ────────────────────────────────────────────────────


def _write_plugin_json(
    state: WizardState,
    project_dir: Path,
    agent_names: list[str],
    skill_names: list[str],
) -> Path:
    """Write .github/plugin/plugin.json."""
    plugin = {
        "name": state.agent_name,
        "description": state.agent_description,
        "version": "1.0.0",
        "author": {"name": "SciAgent Wizard"},
        "license": "MIT",
        "keywords": _derive_keywords(state),
        "agents": ["./agents"],
        "skills": [f"./skills/{name}" for name in skill_names],
    }

    path = project_dir / ".github" / "plugin" / "plugin.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plugin, indent=2) + "\n", encoding="utf-8")
    return path


def _derive_keywords(state: WizardState) -> list[str]:
    """Derive plugin keywords from wizard state."""
    kw = ["scientific-analysis", "data-analysis", "rigor"]
    if state.keywords:
        kw.extend(k.lower().replace(" ", "-") for k in state.keywords[:5])
    for pkg in state.confirmed_packages[:5]:
        kw.append(pkg.name.lower().replace(" ", "-"))
    # De-duplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for k in kw:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique


# ── Plugin README ──────────────────────────────────────────────────────


def _plugin_readme(
    state: WizardState,
    agent_names: list[str],
    skill_names: list[str],
) -> str:
    """Generate README.md for the plugin project."""
    agent_table = "\n".join(
        f"| {name} | `@{name}` |" for name in agent_names
    )
    skill_table = "\n".join(
        f"| {name} | `/{name}` |" for name in skill_names
    )
    pkgs = "\n".join(
        f"- **{p.name}**: {p.description[:80]}"
        for p in state.confirmed_packages
    )

    return f"""\
# {state.agent_display_name} — Copilot Plugin

{state.agent_description}

> Auto-generated by the **sciagent self-assembly wizard**.

**Version**: 1.0.0

## Installation

Add this plugin directory to your VS Code settings:

```jsonc
// settings.json
"chat.plugins.paths": {{
    "/path/to/{state.agent_name}": true
}}
```

## Agents

| Agent | Invocation |
|-------|------------|
{agent_table}

## Skills

| Skill | Slash Command |
|-------|---------------|
{skill_table}

## Domain Packages

{pkgs or "No additional packages configured."}

## What's Included

- **Compiled agent** with inlined domain expertise, scientific rigor principles,
  and handoff suggestions for planning and review workflows.
- **Skills** for scientific rigor enforcement, domain-specific knowledge, and
  per-package API reference.
- **Package documentation** in `docs/` for each confirmed domain library.

## Package Documentation

Local docs for each domain package are in `docs/`.

## Source

Generated by the [SciAgent](https://github.com/smestern/sciagent) self-assembly
wizard.

## License

MIT
"""

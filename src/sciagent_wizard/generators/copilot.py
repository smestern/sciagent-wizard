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
    agents/<prefix>-<name>.md           Compiled agents from templates
    skills/<name>/SKILL.md              Domain skills
    templates/                           Rendered template docs
    docs/                                Package documentation
    README.md
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from sciagent_wizard.models import WizardState
from .docs_gen import write_docs
from .prompt_gen import _build_expertise_text
from sciagent_wizard.rendering import (
    _TEMPLATES_DIR,
    _build_context,
    _humanize_unfilled_placeholders,
    render_docs_with_domain_links,
)

logger = logging.getLogger(__name__)

# ── Template source paths ──────────────────────────────────────────────

_AGENTS_SRC = _TEMPLATES_DIR / "agents" / ".github" / "agents"
_INSTRUCTIONS_SRC = _TEMPLATES_DIR / "agents" / ".github" / "instructions"
_PROMPTS_SRC = _TEMPLATES_DIR / "prompts"
_SKILLS_SRC = _TEMPLATES_DIR / "skills"

# ── Regex patterns ─────────────────────────────────────────────────────

_REPLACE_PATTERN = re.compile(
    r"<!--\s*REPLACE:\s*([a-zA-Z0-9_]+)\s*[—-].*?-->",
    flags=re.DOTALL,
)

# Reference to shared rigor instructions that each agent links to.
_RIGOR_LINK_PATTERN = re.compile(
    r"Follow the \[shared scientific rigor principles\]"
    r"\([^)]*sciagent-rigor\.instructions\.md\)\.",
)

# Which prompt modules to append to each agent.
_AGENT_PROMPT_MAP: dict[str, list[str]] = {
    "coordinator": ["scientific_rigor.md", "communication_style.md", "clarification.md"],
    "analysis-planner": ["scientific_rigor.md", "communication_style.md", "clarification.md"],
    "data-qc": [
        "scientific_rigor.md",
        "communication_style.md",
        "code_execution.md",
        "incremental_execution.md",
        "clarification.md",
    ],
    "rigor-reviewer": ["scientific_rigor.md", "communication_style.md", "clarification.md"],
    "report-writer": [
        "scientific_rigor.md",
        "communication_style.md",
        "reproducible_script.md",
        "clarification.md",
    ],
    "code-reviewer": ["scientific_rigor.md", "communication_style.md", "clarification.md"],
    "docs-ingestor": ["scientific_rigor.md", "communication_style.md", "clarification.md"],
    "coder": [
        "scientific_rigor.md",
        "communication_style.md",
        "code_execution.md",
        "incremental_execution.md",
        "reproducible_script.md",
        "clarification.md",
    ],
}

_BUILTIN_AGENTS = {"agent", "ask"}


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


# ── Template compilation helpers ───────────────────────────────────────


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split YAML frontmatter from markdown body.

    Returns ``(frontmatter_text_without_delimiters, body)``.
    If no frontmatter, returns ``("", text)``.
    """
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return "", text
    end = stripped.find("---", 3)
    if end == -1:
        return "", text
    fm = stripped[3:end].strip()
    body = stripped[end + 3:].lstrip("\n")
    return fm, body


def _apply_replacements(text: str, replacements: dict[str, str]) -> str:
    """Substitute ``<!-- REPLACE: key — … -->`` placeholders in *text*."""
    if not replacements:
        return text

    def _sub(m: re.Match[str]) -> str:
        return replacements.get(m.group(1), m.group(0))

    return _REPLACE_PATTERN.sub(_sub, text)


def _prefixed(name: str, prefix: str) -> str:
    """Return *name* with *prefix*- prepended (or unchanged if prefix is empty)."""
    return f"{prefix}-{name}" if prefix else name


def _compile_agents_from_templates(
    state: WizardState,
    output_dir: Path,
    domain_expertise: str,
) -> list[str]:
    """Compile agent ``.agent.md`` templates into plugin ``agents/<name>.md`` files.

    For each template in ``_AGENTS_SRC``:

    1. Apply ``<!-- REPLACE: … -->`` substitutions from wizard state.
    2. Inline rigor instructions (replace link → full content).
    3. Append prompt modules per ``_AGENT_PROMPT_MAP``.
    4. Prefix ``name:`` and handoff ``agent:`` references with
       ``state.agent_name``.
    5. Append domain expertise text.
    6. Humanize remaining unfilled placeholders.
    7. Write to ``output_dir/agents/<prefixed_name>.md``.

    Returns:
        Sorted list of prefixed agent stems (e.g. ``["myagent-coordinator", …]``).
    """
    name_prefix = state.agent_name

    # Build replacement context from wizard state
    context = _build_context(state)
    replacements: dict[str, str] = dict(context)

    # Load rigor instructions for inlining
    rigor_text = ""
    rigor_path = _INSTRUCTIONS_SRC / "sciagent-rigor.instructions.md"
    if rigor_path.exists():
        rigor_text = rigor_path.read_text(encoding="utf-8").strip()

    # Pre-load prompt modules
    prompt_cache: dict[str, str] = {}
    if _PROMPTS_SRC.exists():
        for p in _PROMPTS_SRC.iterdir():
            if p.suffix == ".md" and p.is_file():
                content = p.read_text(encoding="utf-8").strip()
                _, body = _split_frontmatter(content)
                prompt_cache[p.name] = body.strip() if body.strip() else content

    agents_dir = output_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_names: list[str] = []

    if not _AGENTS_SRC.exists():
        logger.warning("Agent templates not found: %s", _AGENTS_SRC)
        return agent_names

    for src_file in sorted(_AGENTS_SRC.glob("*.agent.md")):
        raw = src_file.read_text(encoding="utf-8")

        # 1. Apply placeholder substitutions
        raw = _apply_replacements(raw, replacements)

        fm_text, body = _split_frontmatter(raw)

        # 2. Inline rigor instructions (replace link with full content)
        if rigor_text:
            replacement_block = (
                "### Shared Scientific Rigor Principles\n\n" + rigor_text
            )
            body = _RIGOR_LINK_PATTERN.sub(replacement_block, body)

        # 3. Append prompt modules
        agent_stem = src_file.stem.replace(".agent", "")
        if agent_stem in _AGENT_PROMPT_MAP:
            appendices: list[str] = []
            for prompt_name in _AGENT_PROMPT_MAP[agent_stem]:
                if prompt_name in prompt_cache:
                    appendices.append(prompt_cache[prompt_name])
            if appendices:
                body = (
                    body.rstrip()
                    + "\n\n---\n\n"
                    + "\n\n---\n\n".join(appendices)
                    + "\n"
                )

        # 4. Append domain expertise
        if domain_expertise:
            body = (
                body.rstrip()
                + "\n\n---\n\n"
                + "## Domain Expertise\n\n"
                + domain_expertise
                + "\n"
            )

        # 5. Name prefixing — update frontmatter name
        prefixed_stem = _prefixed(agent_stem, name_prefix)
        fm_text = re.sub(
            r"^(name:\s*).+$",
            rf"\g<1>{prefixed_stem}",
            fm_text,
            flags=re.MULTILINE,
        )

        # 6. Prefix agent references in handoffs
        if name_prefix:
            fm_text = re.sub(
                r"^(\s*agent:\s*)(.+)$",
                lambda m: (
                    f"{m.group(1)}{m.group(2).strip()}"
                    if m.group(2).strip() in _BUILTIN_AGENTS
                    else f"{m.group(1)}{_prefixed(m.group(2).strip(), name_prefix)}"
                ),
                fm_text,
                flags=re.MULTILINE,
            )

        # 7. Humanize remaining unfilled placeholders
        body = _humanize_unfilled_placeholders(body)

        # Reassemble and write
        output_content = f"---\n{fm_text}\n---\n\n{body}"
        dest = agents_dir / f"{prefixed_stem}.md"
        dest.write_text(output_content, encoding="utf-8")
        agent_names.append(prefixed_stem)
        logger.debug("Compiled agent template %s → %s", src_file.name, dest)

    logger.info("Compiled %d agent templates", len(agent_names))
    return agent_names


def _copy_template_docs(
    state: WizardState,
    output_dir: Path,
) -> list[Path]:
    """Render and copy template documentation files into ``output_dir/templates/``.

    Includes operations.md, workflows.md, tools.md, library_api.md, skills.md
    and prompt modules — all with wizard-state substitutions applied.
    """
    templates_dest = output_dir / "templates"
    written = render_docs_with_domain_links(state, templates_dest)

    # Copy prompt modules
    if _PROMPTS_SRC.exists():
        prompts_dest = templates_dest / "prompts"
        prompts_dest.mkdir(parents=True, exist_ok=True)
        context = _build_context(state)
        for p in sorted(_PROMPTS_SRC.iterdir()):
            if p.suffix == ".md" and p.is_file():
                content = p.read_text(encoding="utf-8")
                content = _apply_replacements(content, context)
                content = _humanize_unfilled_placeholders(content)
                dest = prompts_dest / p.name
                dest.write_text(content, encoding="utf-8")
                written.append(dest)

    return written


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

    Compiles all agent ``.agent.md`` templates from the bundled template
    directory, applying wizard-state substitutions, rigor inlining, prompt
    module appending, name prefixing, and domain expertise injection.

    Produces the plugin directory format that VS Code can discover via
    ``chat.plugins.paths``:

    - ``.github/plugin/plugin.json`` — plugin manifest
    - ``agents/<prefix>-<name>.md`` — compiled agents from templates
    - ``skills/<name>/SKILL.md`` — domain-specific skills
    - ``templates/`` — rendered template docs (operations, workflows, …)
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

    # ── Compile agents from templates ───────────────────────────────
    agent_names = _compile_agents_from_templates(
        state, project_dir, full_instructions
    )

    # ── Build skills ────────────────────────────────────────────────
    skill_names = _build_plugin_skills(state, project_dir, full_instructions)

    # ── Template docs (operations.md, workflows.md, etc.) ──────────
    _copy_template_docs(state, project_dir)

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


# ── Plugin skills ──────────────────────────────────────────────────────


def _build_plugin_skills(
    state: WizardState,
    project_dir: Path,
    full_instructions: str,
) -> list[str]:
    """Generate SKILL.md files for the plugin.

    Copies all built-in skill templates from ``_SKILLS_SRC`` (applying
    placeholder substitutions), then generates dynamic skills:

    - ``domain-expertise`` — domain knowledge extracted from wizard state
    - One skill per confirmed package if package docs are available

    Returns list of skill directory names.
    """
    skills_dir = project_dir / "skills"
    skill_names: list[str] = []

    # Build replacement context for placeholder substitution
    context = _build_context(state)
    replacements: dict[str, str] = dict(context)

    # ── Copy built-in skill templates ───────────────────────────────
    if _SKILLS_SRC.exists():
        for skill_dir in sorted(_SKILLS_SRC.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            content = skill_md.read_text(encoding="utf-8")
            content = _apply_replacements(content, replacements)
            content = _humanize_unfilled_placeholders(content)

            dest = skills_dir / skill_dir.name / "SKILL.md"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            skill_names.append(skill_dir.name)
            logger.debug("Copied skill template %s", skill_dir.name)
    else:
        logger.warning("Skill templates not found: %s", _SKILLS_SRC)

    # ── domain-expertise skill ──────────────────────────────────────
    domain_skill = skills_dir / "domain-expertise" / "SKILL.md"
    domain_skill.parent.mkdir(parents=True, exist_ok=True)
    domain_skill.write_text(
        _domain_expertise_skill_md(state, full_instructions), encoding="utf-8"
    )
    if "domain-expertise" not in skill_names:
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
        if pkg_slug not in skill_names:
            skill_names.append(pkg_slug)

    return skill_names


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
        "agents": [
            f"./agents/{name}.md" for name in agent_names
        ],
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
        f"| `@{name}` | Compiled from template with domain expertise |" for name in agent_names
    )
    skill_table = "\n".join(
        f"| {name} | `/{name}` |" for name in skill_names
    )
    pkgs = "\n".join(
        f"- **{p.name}**: {p.description[:80]}"
        for p in state.confirmed_packages
    )

    n_agents = len(agent_names)
    n_skills = len(skill_names)

    return f"""\
# {state.agent_display_name} — Copilot Plugin

> **{n_agents} specialized agents** and **{n_skills} skills** for
> {state.agent_description}

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

| Agent | Description |
|-------|-------------|
{agent_table}

## Skills

| Skill | Slash Command |
|-------|---------------|
{skill_table}

## Domain Packages

{pkgs or "No additional packages configured."}

## What's Included

- **{n_agents} compiled agents** from SciAgent templates — coordinator, coder,
  analysis-planner, data-qc, rigor-reviewer, report-writer, code-reviewer,
  docs-ingestor, and domain-assembler — each with inlined rigor instructions,
  appended prompt modules, and domain expertise.
- **Skills** for scientific rigor enforcement, domain-specific knowledge, and
  per-package API reference.
- **Template docs** in `templates/` — rendered operations, workflows, tools,
  library API, and skills guides with domain-specific content.
- **Package documentation** in `docs/` for each confirmed domain library.

## Template Documents

Rendered template guides with domain-specific content are in `templates/`.
These include operations.md, workflows.md, tools.md, library_api.md, and
skills.md.

## Package Documentation

Local docs for each domain package are in `docs/`.

## Source

Generated by the [SciAgent](https://github.com/smestern/sciagent) self-assembly
wizard.

## License

MIT
"""

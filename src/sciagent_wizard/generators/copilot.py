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
from typing import Any, Optional

from sciagent_wizard.models import WizardState
from .docs_gen import write_docs
from .prompt_gen import _build_expertise_text
from .profiles import (
    get_profile,
    is_excluded_agent,
    is_excluded_skill,
    REVIEWER_PROMPT_MODULES,
)
from sciagent_wizard.rendering import (
    _get_templates_dir,
    _build_context,
    _humanize_unfilled_placeholders,
    render_docs_with_domain_links,
)

logger = logging.getLogger(__name__)

# ── Template source paths (resolved lazily) ────────────────────────────


def _template_subdir(*parts: str) -> Path:
    """Return ``<templates_dir> / parts``."""
    return _get_templates_dir().joinpath(*parts)


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
    "reviewer": REVIEWER_PROMPT_MODULES,
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

    Compiles all agent templates from the bundled template directory,
    applying wizard-state substitutions, rigor inlining, prompt module
    appending, name prefixing, and domain expertise injection.

    Produces:

    - ``.github/agents/<prefix>-<name>.agent.md`` — VS Code agents
    - ``.claude/agents/<prefix>-<name>.md`` — Claude Code agents
    - ``.github/instructions/<name>.instructions.md`` — Shared instructions
    - ``docs/`` — Package documentation
    - ``README.md``

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

    # ── Compile VS Code agents from templates ───────────────────────
    vscode_agent_names = _compile_agents_from_templates(
        state, project_dir, full_instructions, dest_subdir=".github/agents",
    )

    # ── Compile Claude Code agents from templates ───────────────────
    claude_agent_names = _compile_claude_agents_from_templates(
        state, project_dir, full_instructions,
    )

    # ── Package docs ────────────────────────────────────────────────
    docs_dir = project_dir / "docs"
    render_docs_with_domain_links(state, docs_dir)
    if state.package_docs:
        write_docs(state, docs_dir)

    # ── README ──────────────────────────────────────────────────────
    readme_path = project_dir / "README.md"
    readme_path.write_text(
        _readme(state, vscode_agent_names, claude_agent_names),
        encoding="utf-8",
    )

    state.project_dir = str(project_dir)
    logger.info("Copilot/Claude agent config generated: %s", project_dir)
    return project_dir


# ── VS Code .agent.md ──────────────────────────────────────────────────

_RIGOR_GUARDRAIL_INSTRUCTIONS = """\
### Scientific Rigor — Terminal Usage

Use the terminal for running Python scripts, installing packages, and
environment setup.  Always describe what a terminal command will do
before running it.  Prefer writing scripts to files and executing them
over inline terminal commands for complex analyses.

When analysis produces unexpected, suspicious, or boundary-case results,
flag them prominently to the user and ask for confirmation before
proceeding.  Never silently ignore anomalous results or warnings.
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
    *,
    dest_subdir: str = "agents",
) -> list[str]:
    """Compile agent ``.agent.md`` templates into ``<dest_subdir>/<name>.md`` files.

    Applies profile-aware filtering:

    - Agents in ``exclude_agents`` or consumed by a merge are skipped.
    - Merged agents (e.g. ``reviewer``) are synthesised from their sources.
    - Handoff and body rewrites are applied post-compilation.

    Args:
        state: Populated ``WizardState``.
        output_dir: Root output directory.
        domain_expertise: Pre-built domain expertise text to append.
        dest_subdir: Subdirectory under *output_dir* for compiled agents.
            Defaults to ``"agents"`` (plugin mode).  Pass
            ``".github/agents"`` for copilot-project mode.

    Returns:
        Sorted list of prefixed agent stems (e.g. ``["myagent-coordinator", …]``).
    """
    name_prefix = state.agent_name
    profile = get_profile(state.profile)

    # Build replacement context from wizard state
    context = _build_context(state)
    replacements: dict[str, str] = dict(context)

    # Load rigor instructions for inlining
    rigor_text = ""
    instructions_src = _template_subdir("agents", ".github", "instructions")
    rigor_path = instructions_src / "sciagent-rigor.instructions.md"
    if rigor_path.exists():
        rigor_text = rigor_path.read_text(encoding="utf-8").strip()

    # Pre-load prompt modules
    prompt_cache: dict[str, str] = {}
    prompts_src = _template_subdir("prompts")
    if prompts_src.exists():
        for p in prompts_src.iterdir():
            if p.suffix == ".md" and p.is_file():
                content = p.read_text(encoding="utf-8").strip()
                _, body = _split_frontmatter(content)
                prompt_cache[p.name] = body.strip() if body.strip() else content

    agents_dir = output_dir / dest_subdir
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_names: list[str] = []

    agents_src = _template_subdir("agents", ".github", "agents")
    if not agents_src.exists():
        logger.warning("Agent templates not found: %s", agents_src)
        return agent_names

    for src_file in sorted(agents_src.glob("*.agent.md")):
        agent_stem = src_file.stem.replace(".agent", "")

        # ── Profile filtering — skip excluded / consumed agents ─────
        if is_excluded_agent(agent_stem, profile):
            logger.debug("Skipping excluded agent: %s", agent_stem)
            continue

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

    # ── Produce merged agents ───────────────────────────────────────
    for merged_name, spec in profile.get("merge_agents", {}).items():
        merged_body = _merge_agent_bodies(
            spec, merged_name, replacements, rigor_text,
            prompt_cache, domain_expertise, name_prefix,
        )
        prefixed_stem = _prefixed(merged_name, name_prefix)
        dest = agents_dir / f"{prefixed_stem}.md"
        dest.write_text(merged_body, encoding="utf-8")
        agent_names.append(prefixed_stem)
        logger.debug("Compiled merged agent %s → %s", merged_name, dest)

    # ── Post-process: handoff rewrites ──────────────────────────────
    handoff_rewrites = profile.get("handoff_rewrites", {})
    body_rewrites = profile.get("body_rewrites", {})
    if handoff_rewrites or body_rewrites:
        _apply_post_rewrites(
            agents_dir, agent_names, handoff_rewrites, body_rewrites, name_prefix,
        )

    agent_names.sort()
    logger.info("Compiled %d agent templates", len(agent_names))
    return agent_names


def _merge_agent_bodies(
    spec: dict[str, Any],
    merged_name: str,
    replacements: dict[str, str],
    rigor_text: str,
    prompt_cache: dict[str, str],
    domain_expertise: str,
    name_prefix: str,
) -> str:
    """Synthesise a merged agent from multiple source templates.

    Reads each source ``.agent.md``, applies substitutions and rigor inlining,
    concatenates bodies with ``---`` separator, builds unified YAML frontmatter
    from the merge spec, appends prompt modules (union of sources), and appends
    domain expertise.
    """
    sources = spec["sources"]
    agents_src = _template_subdir("agents", ".github", "agents")

    # Collect bodies from each source
    body_parts: list[str] = []
    seen_prompts: set[str] = set()
    prompt_names: list[str] = []

    for src_name in sources:
        src_file = agents_src / f"{src_name}.agent.md"
        if not src_file.exists():
            logger.warning("Merge source not found: %s", src_file)
            continue

        raw = src_file.read_text(encoding="utf-8")
        raw = _apply_replacements(raw, replacements)
        _, body = _split_frontmatter(raw)

        # Inline rigor
        if rigor_text:
            replacement_block = (
                "### Shared Scientific Rigor Principles\n\n" + rigor_text
            )
            body = _RIGOR_LINK_PATTERN.sub(replacement_block, body)

        body = _humanize_unfilled_placeholders(body)
        body_parts.append(body.strip())

        # Collect prompt modules (union, deduplicated)
        for pname in _AGENT_PROMPT_MAP.get(src_name, []):
            if pname not in seen_prompts:
                seen_prompts.add(pname)
                prompt_names.append(pname)

    # Also add prompt modules for the merged name itself
    for pname in _AGENT_PROMPT_MAP.get(merged_name, []):
        if pname not in seen_prompts:
            seen_prompts.add(pname)
            prompt_names.append(pname)

    merged_body = "\n\n---\n\n".join(body_parts)

    # Append prompt modules
    appendices: list[str] = []
    for pname in prompt_names:
        if pname in prompt_cache:
            appendices.append(prompt_cache[pname])
    if appendices:
        merged_body = (
            merged_body.rstrip()
            + "\n\n---\n\n"
            + "\n\n---\n\n".join(appendices)
            + "\n"
        )

    # Append domain expertise
    if domain_expertise:
        merged_body = (
            merged_body.rstrip()
            + "\n\n---\n\n"
            + "## Domain Expertise\n\n"
            + domain_expertise
            + "\n"
        )

    # Build unified frontmatter
    prefixed_stem = _prefixed(merged_name, name_prefix)
    fm_lines = [
        f"name: {prefixed_stem}",
        "description: >-",
        f"  {spec['description']}",
    ]
    if spec.get("argument_hint"):
        fm_lines.append(f"argument-hint: \"{spec['argument_hint']}\"")
    if spec.get("tools"):
        fm_lines.append("tools:")
        for t in spec["tools"]:
            fm_lines.append(f"  - {t}")
    if spec.get("handoffs"):
        fm_lines.append("handoffs:")
        for ho in spec["handoffs"]:
            agent_ref = ho["agent"]
            if name_prefix and agent_ref not in _BUILTIN_AGENTS:
                agent_ref = _prefixed(agent_ref, name_prefix)
            fm_lines.append(f"  - label: \"{ho['label']}\"")
            fm_lines.append(f"    agent: {agent_ref}")
            fm_lines.append(f"    prompt: \"{ho['prompt']}\"")
            send_val = "true" if ho.get("send") else "false"
            fm_lines.append(f"    send: {send_val}")

    fm_text = "\n".join(fm_lines)
    return f"---\n{fm_text}\n---\n\n{merged_body}"


def _apply_post_rewrites(
    agents_dir: Path,
    agent_names: list[str],
    handoff_rewrites: dict[str, str | None],
    body_rewrites: dict[str, str],
    name_prefix: str,
) -> None:
    """Post-process compiled agent files to fix handoff refs and body text.

    - ``handoff_rewrites``: maps old agent stem → new stem (or ``None`` to
      remove the handoff entirely).
    - ``body_rewrites``: plain-text substitutions in agent body content.
    """
    # Build prefixed versions of the rewrite keys
    prefixed_handoff: dict[str, str | None] = {}
    for old, new in handoff_rewrites.items():
        p_old = _prefixed(old, name_prefix) if name_prefix else old
        p_new = _prefixed(new, name_prefix) if (new and name_prefix) else new
        prefixed_handoff[p_old] = p_new

    prefixed_body: dict[str, str] = {}
    for old, new in body_rewrites.items():
        if old.startswith("@") and name_prefix:
            p_old = f"@{_prefixed(old[1:], name_prefix)}"
            if new.startswith("@"):
                p_new = f"@{_prefixed(new[1:], name_prefix)}"
            else:
                p_new = new
        else:
            p_old = old
            p_new = new
        prefixed_body[p_old] = p_new

    for agent_stem in agent_names:
        path = agents_dir / f"{agent_stem}.md"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        fm_text, body = _split_frontmatter(text)
        changed = False

        # Handoff rewrites in frontmatter
        if prefixed_handoff:
            new_fm_lines: list[str] = []
            fm_lines_list = fm_text.splitlines()
            i = 0
            while i < len(fm_lines_list):
                line = fm_lines_list[i]
                # Detect `agent: <name>` in handoffs
                m = re.match(r"^(\s*agent:\s*)(.+)$", line)
                if m:
                    ref = m.group(2).strip()
                    if ref in prefixed_handoff:
                        replacement = prefixed_handoff[ref]
                        if replacement is None:
                            # Remove entire handoff block — backtrack to
                            # remove the `- label:` line and following lines
                            # (agent, prompt, send)
                            while new_fm_lines and not re.match(
                                r"^\s*- label:", new_fm_lines[-1]
                            ):
                                new_fm_lines.pop()
                            if new_fm_lines and re.match(
                                r"^\s*- label:", new_fm_lines[-1]
                            ):
                                new_fm_lines.pop()
                            # Skip remaining lines of this handoff entry
                            i += 1
                            while i < len(fm_lines_list) and re.match(
                                r"^\s+(prompt|send):", fm_lines_list[i]
                            ):
                                i += 1
                            changed = True
                            continue
                        else:
                            # Check for duplicate — skip if another handoff
                            # already references the same target
                            already_has = any(
                                re.match(
                                    rf"^\s*agent:\s*{re.escape(replacement)}\s*$",
                                    ln,
                                )
                                for ln in new_fm_lines
                            )
                            if already_has:
                                # Remove this duplicate handoff block
                                while new_fm_lines and not re.match(
                                    r"^\s*- label:", new_fm_lines[-1]
                                ):
                                    new_fm_lines.pop()
                                if new_fm_lines and re.match(
                                    r"^\s*- label:", new_fm_lines[-1]
                                ):
                                    new_fm_lines.pop()
                                i += 1
                                while i < len(fm_lines_list) and re.match(
                                    r"^\s+(prompt|send):", fm_lines_list[i]
                                ):
                                    i += 1
                                changed = True
                                continue
                            else:
                                line = f"{m.group(1)}{replacement}"
                                changed = True
                new_fm_lines.append(line)
                i += 1
            if changed:
                fm_text = "\n".join(new_fm_lines)

        # Body rewrites
        new_body = body
        for old_txt, new_txt in prefixed_body.items():
            if old_txt in new_body:
                new_body = new_body.replace(old_txt, new_txt)
                changed = True

        if changed:
            path.write_text(f"---\n{fm_text}\n---\n\n{new_body}", encoding="utf-8")


def _compile_claude_agents_from_templates(
    state: WizardState,
    output_dir: Path,
    domain_expertise: str,
) -> list[str]:
    """Compile Claude Code agent templates into ``.claude/agents/<name>.md``.

    Claude templates are self-contained (inline rigor, no prompt module
    appending).  Compilation applies profile-aware filtering:

    - Agents in ``exclude_agents`` or consumed by a merge are skipped.
    - Merged agents (e.g. ``reviewer``) are synthesised from their sources.
    - Handoff and body rewrites are applied post-compilation.

    Returns:
        Sorted list of prefixed agent stems.
    """
    name_prefix = state.agent_name
    profile = get_profile(state.profile)

    claude_dir = output_dir / ".claude" / "agents"
    claude_dir.mkdir(parents=True, exist_ok=True)
    agent_names: list[str] = []

    claude_agents_src = _template_subdir("agents", ".claude", "agents")
    if not claude_agents_src.exists():
        logger.warning("Claude agent templates not found: %s", claude_agents_src)
        return agent_names

    for src_file in sorted(claude_agents_src.glob("*.md")):
        raw = src_file.read_text(encoding="utf-8")
        fm_text, body = _split_frontmatter(raw)

        # Derive a clean stem, stripping any pre-existing "sciagent-" prefix
        agent_stem = src_file.stem
        if agent_stem.startswith("sciagent-"):
            agent_stem = agent_stem[len("sciagent-"):]

        # ── Profile filtering — skip excluded / consumed agents ─────
        if is_excluded_agent(agent_stem, profile):
            logger.debug("Skipping excluded Claude agent: %s", agent_stem)
            continue

        # 1. Name prefixing
        prefixed_stem = _prefixed(agent_stem, name_prefix)
        fm_text = re.sub(
            r"^(name:\s*).+$",
            rf"\g<1>{prefixed_stem}",
            fm_text,
            flags=re.MULTILINE,
        )

        # 2. Append domain expertise
        if domain_expertise:
            body = (
                body.rstrip()
                + "\n\n---\n\n"
                + "## Domain Expertise\n\n"
                + domain_expertise
                + "\n"
            )

        # 3. Humanize remaining unfilled placeholders
        body = _humanize_unfilled_placeholders(body)

        # Reassemble and write
        output_content = f"---\n{fm_text}\n---\n\n{body}"
        dest = claude_dir / f"{prefixed_stem}.md"
        dest.write_text(output_content, encoding="utf-8")
        agent_names.append(prefixed_stem)
        logger.debug("Compiled Claude agent template %s → %s", src_file.name, dest)

    # ── Produce merged agents for Claude ────────────────────────────
    for merged_name, spec in profile.get("merge_agents", {}).items():
        merged_body = _merge_claude_agent_bodies(
            spec, merged_name, domain_expertise, name_prefix,
        )
        if merged_body:
            prefixed_stem = _prefixed(merged_name, name_prefix)
            dest = claude_dir / f"{prefixed_stem}.md"
            dest.write_text(merged_body, encoding="utf-8")
            agent_names.append(prefixed_stem)
            logger.debug("Compiled merged Claude agent %s → %s", merged_name, dest)

    # ── Post-process: handoff rewrites + body rewrites ──────────────
    handoff_rewrites = profile.get("handoff_rewrites", {})
    body_rewrites = profile.get("body_rewrites", {})
    if handoff_rewrites or body_rewrites:
        _apply_post_rewrites(
            claude_dir, agent_names, handoff_rewrites, body_rewrites, name_prefix,
        )

    agent_names.sort()
    logger.info("Compiled %d Claude agent templates", len(agent_names))
    return agent_names


def _merge_claude_agent_bodies(
    spec: dict[str, Any],
    merged_name: str,
    domain_expertise: str,
    name_prefix: str,
) -> str | None:
    """Synthesise a merged Claude agent from multiple source templates.

    Claude templates are self-contained markdown (no prompt module appending).
    Returns the full file content, or ``None`` if no sources found.
    """
    sources = spec["sources"]
    claude_src = _template_subdir("agents", ".claude", "agents")
    if not claude_src.exists():
        return None

    body_parts: list[str] = []
    for src_name in sources:
        # Claude files may use "sciagent-" prefix
        candidates = [
            claude_src / f"{src_name}.md",
            claude_src / f"sciagent-{src_name}.md",
        ]
        src_file = next((c for c in candidates if c.exists()), None)
        if not src_file:
            logger.warning("Claude merge source not found: %s", src_name)
            continue
        raw = src_file.read_text(encoding="utf-8")
        _, body = _split_frontmatter(raw)
        body = _humanize_unfilled_placeholders(body)
        body_parts.append(body.strip())

    if not body_parts:
        return None

    merged_body = "\n\n---\n\n".join(body_parts)
    if domain_expertise:
        merged_body = (
            merged_body.rstrip()
            + "\n\n---\n\n"
            + "## Domain Expertise\n\n"
            + domain_expertise
            + "\n"
        )

    prefixed_stem = _prefixed(merged_name, name_prefix)
    fm_lines = [
        f"name: {prefixed_stem}",
        "description: >-",
        f"  {spec['description']}",
    ]
    fm_text = "\n".join(fm_lines)
    return f"---\n{fm_text}\n---\n\n{merged_body}"


def _merge_skill_bodies(
    merged_name: str,
    spec: dict[str, Any],
    skills_src: Path,
    replacements: dict[str, str],
) -> str | None:
    """Merge multiple skill SKILL.md templates into one.

    *spec* has ``sources`` (list of skill dir names), ``description``
    (override or None to keep original), and ``section_titles`` mapping
    each source → optional heading (None keeps content as-is).
    """
    sources: list[str] = spec.get("sources", [])
    section_titles: dict[str, str | None] = spec.get("section_titles", {})
    body_parts: list[str] = []
    first_fm: dict[str, str] = {}

    for src_name in sources:
        src_file = skills_src / src_name / "SKILL.md"
        if not src_file.exists():
            logger.warning("Merge skill source not found: %s", src_name)
            continue
        raw = src_file.read_text(encoding="utf-8")
        raw = _apply_replacements(raw, replacements)
        raw = _humanize_unfilled_placeholders(raw)
        fm_text, body = _split_frontmatter(raw)
        if not first_fm and fm_text:
            # Parse first source's frontmatter for fallback description
            for line in fm_text.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    first_fm[k.strip()] = v.strip()

        title = section_titles.get(src_name, src_name)
        if title:
            body_parts.append(f"## {title}\n\n{body.strip()}")
        else:
            body_parts.append(body.strip())

    if not body_parts:
        return None

    merged_body = "\n\n---\n\n".join(body_parts)

    # Build frontmatter
    desc = spec.get("description") or first_fm.get("description", "")
    fm_lines = [
        f"name: {merged_name}",
        "description: >-",
        f"  {desc}",
    ]
    return "---\n" + "\n".join(fm_lines) + "\n---\n\n" + merged_body + "\n"


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
    prompts_src = _template_subdir("prompts")
    if prompts_src.exists():
        prompts_dest = templates_dest / "prompts"
        prompts_dest.mkdir(parents=True, exist_ok=True)
        context = _build_context(state)
        for p in sorted(prompts_src.iterdir()):
            if p.suffix == ".md" and p.is_file():
                content = p.read_text(encoding="utf-8")
                content = _apply_replacements(content, context)
                content = _humanize_unfilled_placeholders(content)
                dest = prompts_dest / p.name
                dest.write_text(content, encoding="utf-8")
                written.append(dest)

    return written


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


def _readme(
    state: WizardState,
    vscode_agent_names: list[str] | None = None,
    claude_agent_names: list[str] | None = None,
) -> str:
    """Generate a README for the copilot/claude agent project."""
    slug = state.agent_name
    pkgs = "\n".join(
        f"- **{p.name}**: {p.description[:80]}"
        for p in state.confirmed_packages
    )

    vscode_names = vscode_agent_names or []
    claude_names = claude_agent_names or []

    vscode_list = (
        "\n".join(f"- `@{n}`" for n in vscode_names)
        if vscode_names
        else f"- `@{slug}`"
    )
    claude_list = (
        "\n".join(f"- `{n}`" for n in claude_names)
        if claude_names
        else f"- `{slug}`"
    )

    return f"""\
# {state.agent_display_name}

{state.agent_description}

> Auto-generated by the **sciagent self-assembly wizard**.

## Output Mode: Copilot / Claude Code Agent

This project contains **{len(vscode_names)} VS Code agents** and
**{len(claude_names)} Claude Code agents** compiled from SciAgent templates
with domain-specific expertise.

### VS Code GitHub Copilot

Agents are in `.github/agents/`:

{vscode_list}

To use them:
1. Copy this project into your workspace
2. Open VS Code with GitHub Copilot enabled
3. Select an agent from the Agents dropdown in chat (e.g. `@{slug}-coordinator`)

### Claude Code

Agents are in `.claude/agents/`:

{claude_list}

To use them:
1. Copy the `.claude/agents/` folder into your project
2. Run Claude Code — it will auto-detect the sub-agents

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

    Copies built-in skill templates (applying placeholder substitutions),
    filters and merges them according to the active profile, then generates
    dynamic skills:

    - ``domain-expertise`` — domain knowledge extracted from wizard state
    - One skill per confirmed package if package docs are available

    Returns list of skill directory names.
    """
    profile = get_profile(state.profile)
    skills_dir = project_dir / "skills"
    skill_names: list[str] = []

    # Build replacement context for placeholder substitution
    context = _build_context(state)
    replacements: dict[str, str] = dict(context)

    # ── Copy built-in skill templates (profile-filtered) ────────────
    skills_src = _template_subdir("skills")
    if skills_src.exists():
        for skill_dir in sorted(skills_src.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            if is_excluded_skill(skill_dir.name, profile):
                logger.debug("Skipping excluded/consumed skill %s", skill_dir.name)
                continue

            content = skill_md.read_text(encoding="utf-8")
            content = _apply_replacements(content, replacements)
            content = _humanize_unfilled_placeholders(content)

            dest = skills_dir / skill_dir.name / "SKILL.md"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            skill_names.append(skill_dir.name)
            logger.debug("Copied skill template %s", skill_dir.name)

        # ── Produce merged skills ───────────────────────────────────
        for merged_name, spec in profile.get("merge_skills", {}).items():
            merged_content = _merge_skill_bodies(
                merged_name, spec, skills_src, replacements
            )
            if merged_content is None:
                continue
            # If the merged name already exists (self-merge like
            # configure-domain), overwrite it with the merged version.
            dest = skills_dir / merged_name / "SKILL.md"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(merged_content, encoding="utf-8")
            if merged_name not in skill_names:
                skill_names.append(merged_name)
            logger.debug("Wrote merged skill %s", merged_name)
    else:
        logger.warning("Skill templates not found: %s", skills_src)

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

    agent_short_names = ", ".join(
        n.removeprefix(state.agent_name + "-") if n.startswith(state.agent_name + "-") else n
        for n in agent_names
    )

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

- **{n_agents} compiled agents** from SciAgent templates — {agent_short_names} — each with inlined rigor instructions,
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

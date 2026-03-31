"""
copilot_adapter — Subprocess wrapper around ``scripts/build_plugin.py``.

This module replaces the direct template-compilation logic that was
previously duplicated in ``copilot.py``.  Instead it:

1. Serialises wizard state into temp files (replacements JSON, domain
   expertise markdown, extra skills, extra docs).
2. Shells out to ``build_plugin.py --platform both`` with the new
   ``--domain-expertise-file``, ``--extra-skills-dir``, and
   ``--extra-docs-dir`` flags.
3. Writes a wizard-specific README over the generic one.

The ``generate_copilot_via_build`` function is the single entry point.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from sciagent_wizard.models import WizardState
from sciagent_wizard.rendering import (
    _get_templates_dir,
    _build_context,
    render_docs_with_domain_links,
)
from .prompt_gen import _build_expertise_text
from .docs_gen import write_docs

logger = logging.getLogger(__name__)


# ── Script discovery ────────────────────────────────────────────────────

def _find_build_command() -> list[str]:
    """Return the command prefix to invoke ``build_plugin.py``.

    Resolution order:

    1. ``<templates_dir>/../scripts/build_plugin.py`` — editable install or
       source tree.
    2. Dev monorepo: ``<wizard_repo>/../../sciagent/scripts/``.
    3. ``shutil.which("sciagent-build")`` — console_scripts entry point.
    4. ``python -m sciagent.scripts.build_plugin`` — pip-installed package.

    Returns a list suitable as the prefix of a :func:`subprocess.run` call
    (e.g. ``[sys.executable, "/path/to/build_plugin.py"]`` or
    ``[sys.executable, "-m", "sciagent.scripts.build_plugin"]``).

    Raises ``FileNotFoundError`` if none of the methods succeed.
    """
    # 1. Relative to templates dir (editable / source tree)
    try:
        templates = _get_templates_dir()
        candidate = templates.parent / "scripts" / "build_plugin.py"
        if candidate.is_file():
            return [sys.executable, str(candidate)]
    except FileNotFoundError:
        pass

    # 2. Dev monorepo: sciagent-wizard sits next to sciagent
    _dev_candidates = [
        Path(__file__).resolve().parents[4] / "sciagent" / "scripts" / "build_plugin.py",
        Path(__file__).resolve().parents[3] / "scripts" / "build_plugin.py",
    ]
    for candidate in _dev_candidates:
        if candidate.is_file():
            return [sys.executable, str(candidate)]

    # 3. Console scripts entry point
    which = shutil.which("sciagent-build")
    if which:
        return [which]

    # 4. Packaged module (pip install sciagent)
    try:
        import sciagent.scripts.build_plugin  # noqa: F401
        return [sys.executable, "-m", "sciagent.scripts.build_plugin"]
    except ImportError:
        pass

    raise FileNotFoundError(
        "Cannot locate build_plugin.py.  Ensure sciagent is installed "
        "(pip install sciagent) or that scripts/build_plugin.py exists."
    )


# ── Dynamic skill builders ─────────────────────────────────────────────

def _domain_expertise_skill_md(state: WizardState, instructions: str) -> str:
    """Generate a domain-expertise SKILL.md wrapping the expertise text."""
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
    """Generate a per-package SKILL.md with API reference."""
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


# ── README ──────────────────────────────────────────────────────────────

def _plugin_readme(
    state: WizardState,
    agent_names: list[str],
    skill_names: list[str],
) -> str:
    """Generate a wizard-specific README for the plugin."""
    slug = state.agent_name
    pkgs = "\n".join(
        f"- **{p.name}**: {p.description[:80]}"
        for p in state.confirmed_packages
    )
    agent_list = "\n".join(f"- `@{n}`" for n in agent_names)
    skill_list = "\n".join(f"- `/{n}`" for n in skill_names)

    return f"""\
# {state.agent_display_name}

{state.agent_description}

> Auto-generated by the **sciagent self-assembly wizard**.

## Installation

Add to VS Code `settings.json`:

```json
"chat.plugins.paths": {{
    "{slug}": true
}}
```

Restart VS Code, then invoke `@{slug}` in Copilot chat.

### Claude Code

Claude Code agents are also included under the `.claude/` subdirectory:

```bash
claude --plugin-dir ./{slug}/.claude
```

## Agents

{agent_list or f"- `@{slug}`"}

## Skills

{skill_list or "(none)"}

## Domain Packages

{pkgs or "No additional packages configured."}
"""


# ── Main entry point ───────────────────────────────────────────────────

def generate_copilot_via_build(
    state: WizardState,
    output_dir: Optional[str | Path] = None,
) -> Path:
    """Generate a Copilot + Claude Code plugin by calling ``build_plugin.py``.

    Args:
        state: Populated ``WizardState``.
        output_dir: Parent directory. Defaults to CWD.

    Returns:
        Path to the generated plugin directory.
    """
    build_cmd = _find_build_command()
    base = Path(output_dir) if output_dir else Path.cwd()
    slug = state.agent_name.replace(" ", "_").replace("-", "_")
    project_dir = base / slug
    project_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Generating copilot plugin via build_plugin.py → %s", project_dir)

    # ── Assemble domain expertise ───────────────────────────────────
    expertise = _build_expertise_text(state)
    docs_ref = _docs_reference(state)
    full_instructions = expertise
    if docs_ref:
        full_instructions += "\n\n" + docs_ref

    # ── Build replacements dict from state ──────────────────────────
    replacements = _build_context(state)

    # ── Prepare temp artefacts ──────────────────────────────────────
    with tempfile.TemporaryDirectory(prefix="sciagent-build-") as tmpdir:
        tmp = Path(tmpdir)

        # 1. Replacements JSON
        replacements_file = tmp / "replacements.json"
        replacements_file.write_text(
            json.dumps(replacements, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # 2. Domain expertise file
        expertise_file = tmp / "domain_expertise.md"
        expertise_file.write_text(full_instructions, encoding="utf-8")

        # 3. Extra skills directory (domain-expertise + per-package)
        extra_skills = tmp / "extra_skills"
        extra_skills.mkdir()

        # Domain expertise skill (not user-invokable, auto-loaded)
        de_skill = extra_skills / "domain-expertise"
        de_skill.mkdir()
        (de_skill / "SKILL.md").write_text(
            _domain_expertise_skill_md(state, full_instructions),
            encoding="utf-8",
        )

        # Per-package skills
        for pkg in state.confirmed_packages:
            doc = state.package_docs.get(pkg.name, "")
            api_doc = state.package_docs.get(f"{pkg.name}_api", "")
            combined = "\n\n".join(filter(None, [doc, api_doc]))
            if not combined:
                continue
            pkg_slug = pkg.name.lower().replace(" ", "-").replace("_", "-")
            pkg_dir = extra_skills / pkg_slug
            pkg_dir.mkdir(exist_ok=True)
            (pkg_dir / "SKILL.md").write_text(
                _package_skill_md(pkg.name, pkg.description, combined),
                encoding="utf-8",
            )

        # 4. Extra docs directory
        extra_docs = tmp / "extra_docs"
        extra_docs.mkdir()
        render_docs_with_domain_links(state, extra_docs)
        if state.package_docs:
            write_docs(state, extra_docs)

        # ── Resolve profile ─────────────────────────────────────────
        profile = getattr(state, "profile", "full")

        # ── Resolve name prefix ─────────────────────────────────────
        name_prefix = state.agent_name or ""

        # ── Call build_plugin.py ────────────────────────────────────
        # Build into temp subdirs, then merge into project_dir.
        # --force causes shutil.rmtree so Copilot and Claude outputs
        # must be kept separate during the build.
        copilot_out = tmp / "copilot_out"
        claude_out = tmp / "claude_out"

        cmd = build_cmd + [
            "--output", str(copilot_out),
            "--claude-output", str(claude_out),
            "--platform", "both",
            "--profile", profile,
            "--name-prefix", name_prefix,
            "--replacements-file", str(replacements_file),
            "--domain-expertise-file", str(expertise_file),
            "--extra-skills-dir", str(extra_skills),
            "--extra-docs-dir", str(extra_docs),
            "--force",
        ]

        logger.info("Running: %s", " ".join(cmd))
        env = {**__import__("os").environ, "PYTHONUTF8": "1"}
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=120,
        )

        if result.returncode != 0:
            logger.error("build_plugin.py failed:\n%s", result.stderr)
            raise RuntimeError(
                f"build_plugin.py exited with code {result.returncode}:\n"
                f"{result.stderr}"
            )

        logger.info("build_plugin.py output:\n%s", result.stdout)

        # ── Merge Copilot + Claude outputs into project_dir ─────────
        # Copilot output is the primary base.
        if project_dir.exists():
            shutil.rmtree(project_dir)
        shutil.copytree(copilot_out, project_dir, dirs_exist_ok=True)
        # Place the entire Claude output under .claude/ so its agents/
        # and skills/ (which use Claude-format frontmatter) don't
        # overwrite the Copilot versions.
        claude_dest = project_dir / ".claude"
        shutil.copytree(claude_out, claude_dest, dirs_exist_ok=True)

    # ── Collect output file names for README ────────────────────────
    agents_dir = project_dir / "agents"
    agent_names = sorted(
        f.stem for f in agents_dir.glob("*.md") if f.is_file()
    ) if agents_dir.is_dir() else []

    skills_dir = project_dir / "skills"
    skill_names = sorted(
        d.name for d in skills_dir.iterdir()
        if d.is_dir() and (d / "SKILL.md").is_file()
    ) if skills_dir.is_dir() else []

    # ── Overwrite README with wizard-specific version ───────────────
    readme_path = project_dir / "README.md"
    readme_path.write_text(
        _plugin_readme(state, agent_names, skill_names),
        encoding="utf-8",
    )

    state.project_dir = str(project_dir)
    logger.info("Copilot plugin generated: %s", project_dir)
    return project_dir

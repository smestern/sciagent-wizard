"""
sciagent_wizard.generators — Generate a complete agent project from wizard state.

The ``generate_project`` function is the single entry point: it dispatches
on ``state.output_mode`` to call the appropriate generator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sciagent_wizard.models import OutputMode, WizardState

from .fullstack import generate_project as generate_fullstack_project
from .copilot_adapter import generate_copilot_via_build as generate_copilot_plugin
from .copilot import generate_copilot_plugin as _generate_copilot_plugin_legacy
from .markdown import generate_markdown_project
from .docs_gen import write_docs
from sciagent_wizard.rendering import (
    render_docs,
    render_template,
    copy_blank_templates,
)


def generate_project(
    state: WizardState,
    output_dir: Optional[str | Path] = None,
) -> Path:
    """Generate an agent project, dispatching on ``state.output_mode``.

    Args:
        state: Populated ``WizardState`` from the wizard conversation.
        output_dir: Parent directory for the project. Defaults to CWD.

    Returns:
        Path to the generated project directory.
    """
    mode = state.output_mode

    if mode == OutputMode.COPILOT:
        return generate_copilot_plugin(state, output_dir=output_dir)

    if mode == OutputMode.MARKDOWN:
        return generate_markdown_project(state, output_dir=output_dir)

    # Default: FULLSTACK
    return generate_fullstack_project(state, output_dir=output_dir)


__all__ = [
    "generate_project",
    "generate_fullstack_project",
    "generate_copilot_plugin",
    "generate_markdown_project",
    "write_docs",
    "render_docs",
    "render_template",
    "copy_blank_templates",
]

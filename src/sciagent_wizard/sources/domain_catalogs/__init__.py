"""
Pre-generated domain package catalogs.

Provides curated lists of scientific packages for common research
domains so the wizard can instantly recommend known-good tools without
running live network searches every time.

Each domain is stored as a separate JSON file in this directory (e.g.
``electrophysiology.json``).  Community contributions are welcome —
see ``CONTRIBUTING_CATALOGS.md`` for the schema and guidelines.

Usage::

    from sciagent_wizard.sources.domain_catalogs import (
        list_catalogs,
        load_catalog,
    )

    # Show available domains
    catalogs = list_catalogs()

    # Load packages for a specific domain
    packages = load_catalog("electrophysiology")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from sciagent_wizard.models import DiscoverySource, PackageCandidate

logger = logging.getLogger(__name__)

_CATALOG_DIR = Path(__file__).parent


# ── Public API ──────────────────────────────────────────────────────────


def list_catalogs() -> List[Dict[str, Any]]:
    """Return metadata for every available domain catalog.

    Each entry contains ``domain``, ``display_name``, ``description``,
    and ``keywords`` — everything the LLM needs to decide whether a
    catalog matches the researcher's domain.  Package lists are *not*
    loaded here (use :func:`load_catalog` for that).
    """
    catalogs: list[dict[str, Any]] = []
    for path in sorted(_CATALOG_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            catalogs.append({
                "domain": data.get("domain", path.stem),
                "display_name": data.get("display_name", path.stem),
                "description": data.get("description", ""),
                "keywords": data.get("keywords", []),
                "package_count": len(data.get("packages", [])),
            })
        except Exception as exc:
            logger.warning("Skipping invalid catalog %s: %s", path.name, exc)
    return catalogs


def load_catalog(domain_slug: str) -> List[PackageCandidate]:
    """Load packages from a pre-generated domain catalog.

    Args:
        domain_slug: The domain identifier (matches the JSON filename
            without extension, e.g. ``"electrophysiology"``).

    Returns:
        List of ``PackageCandidate`` objects with
        ``source=DiscoverySource.CACHED``.

    Raises:
        FileNotFoundError: If no catalog exists for *domain_slug*.
        ValueError: If the catalog JSON is malformed.
    """
    path = _CATALOG_DIR / f"{domain_slug}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No domain catalog found for '{domain_slug}'. "
            f"Available: {[p.stem for p in _CATALOG_DIR.glob('*.json')]}"
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    raw_packages = data.get("packages", [])
    if not isinstance(raw_packages, list):
        raise ValueError(
            f"Catalog '{domain_slug}' has invalid 'packages' field "
            f"(expected list, got {type(raw_packages).__name__})"
        )

    candidates: list[PackageCandidate] = []
    for pkg in raw_packages:
        try:
            candidates.append(_deserialize_package(pkg))
        except Exception as exc:
            logger.warning(
                "Skipping invalid package entry in %s catalog: %s",
                domain_slug,
                exc,
            )

    logger.info(
        "Loaded %d packages from '%s' domain catalog",
        len(candidates),
        domain_slug,
    )
    return candidates


def validate_catalog(path: str | Path) -> List[str]:
    """Check a catalog JSON file for schema errors.

    Returns a list of error messages (empty = valid).
    """
    path = Path(path)
    errors: list[str] = []

    if not path.exists():
        return [f"File not found: {path}"]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid JSON: {exc}"]

    # Required top-level fields
    for field in ("domain", "display_name", "description", "keywords", "packages"):
        if field not in data:
            errors.append(f"Missing required field: '{field}'")

    if "keywords" in data and not isinstance(data["keywords"], list):
        errors.append("'keywords' must be a list of strings")

    if "packages" in data:
        if not isinstance(data["packages"], list):
            errors.append("'packages' must be a list")
        else:
            for i, pkg in enumerate(data["packages"]):
                if not isinstance(pkg, dict):
                    errors.append(f"packages[{i}] must be a dict")
                    continue
                if "name" not in pkg:
                    errors.append(f"packages[{i}] missing 'name'")
                score = pkg.get("relevance_score", 0)
                if not isinstance(score, (int, float)) or score < 0 or score > 1:
                    errors.append(
                        f"packages[{i}] ({pkg.get('name', '?')}): "
                        f"relevance_score must be 0–1, got {score}"
                    )

    return errors


# ── Internal helpers ────────────────────────────────────────────────────


def _deserialize_package(raw: dict) -> PackageCandidate:
    """Convert a catalog JSON entry to a PackageCandidate."""
    return PackageCandidate(
        name=raw["name"],
        source=DiscoverySource.CACHED,
        description=raw.get("description", ""),
        install_command=raw.get("install_command", ""),
        homepage=raw.get("homepage", ""),
        repository_url=raw.get("repository_url", ""),
        citations=raw.get("citations", 0),
        downloads=raw.get("downloads", 0),
        relevance_score=raw.get("relevance_score", 0.0),
        peer_reviewed=raw.get("peer_reviewed", False),
        publication_dois=raw.get("publication_dois", []),
        keywords=raw.get("keywords", []),
        python_package=raw.get("python_package", ""),
    )

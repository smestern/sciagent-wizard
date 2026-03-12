#!/usr/bin/env python
"""
Generate (or regenerate) a domain package catalog by running the live
discovery pipeline and saving the results as a JSON file.

Usage
-----
Generate a new catalog::

    python scripts/generate_domain_catalog.py \\
        --domain electrophysiology \\
        --keywords "patch-clamp,ABF,action potential,ion channel,electrophysiology" \\
        --queries "patch clamp python package,ABF analysis software python" \\
        --display-name "Electrophysiology"

Regenerate all existing catalogs (re-runs discovery using each JSON's
stored keywords)::

    python scripts/generate_domain_catalog.py --all

Preview without writing::

    python scripts/generate_domain_catalog.py --domain test --keywords "test" --dry-run

Validate an existing catalog::

    python scripts/generate_domain_catalog.py --validate path/to/catalog.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure sciagent-wizard is importable when running from the repo root
_WIZARD_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_WIZARD_SRC) not in sys.path:
    sys.path.insert(0, str(_WIZARD_SRC))

from sciagent_wizard.sources.ranker import discover_packages  # noqa: E402
from sciagent_wizard.sources.domain_catalogs import (  # noqa: E402
    validate_catalog,
    _CATALOG_DIR,
)

GENERATOR_VERSION = "1.0"


def _build_catalog_dict(
    domain: str,
    display_name: str,
    description: str,
    keywords: list[str],
    packages: list,
) -> dict:
    """Build the JSON-serializable catalog dict."""
    pkg_dicts = []
    for p in packages:
        pkg_dicts.append({
            "name": p.name,
            "python_package": p.python_package,
            "description": p.description[:300],
            "install_command": p.install_command,
            "homepage": p.homepage,
            "repository_url": p.repository_url,
            "relevance_score": round(p.relevance_score, 3),
            "peer_reviewed": p.peer_reviewed,
            "citations": p.citations,
            "downloads": p.downloads,
            "publication_dois": p.publication_dois,
            "keywords": p.keywords,
        })

    return {
        "domain": domain,
        "display_name": display_name,
        "description": description,
        "keywords": keywords,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator_version": GENERATOR_VERSION,
        "packages": pkg_dicts,
    }


# ── Expanded query generation for catalogs ─────────────────────────────

_CATALOG_SUFFIXES = [
    "python package",
    "analysis software",
    "python library",
    "python tool",
    "open source software",
]


def _expand_queries(keywords: list[str], extra_queries: list[str] | None = None) -> list[str]:
    """Generate many targeted search phrases from keywords.

    Unlike the wizard's live search (2-3 queries), catalog generation
    runs an expanded search to build a comprehensive list.  We pair
    each keyword (or pair of keywords) with multiple software-oriented
    suffixes, then append any explicit extra queries.
    """
    queries: list[str] = []
    # Pair keywords with suffixes
    for kw in keywords:
        for suffix in _CATALOG_SUFFIXES:
            queries.append(f"{kw} {suffix}")
    # Pair adjacent keywords for richer phrases
    for i in range(len(keywords) - 1):
        queries.append(f"{keywords[i]} {keywords[i+1]} python package")
    # Add caller-provided queries
    if extra_queries:
        queries.extend(extra_queries)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        key = q.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(q)
    return unique


def _run_discovery(
    keywords: list[str],
    queries: list[str] | None = None,
    max_per_source: int = 50,
) -> list:
    """Run the full async discovery pipeline synchronously.

    Uses higher per-source caps and expanded queries compared to the
    wizard's live search, since catalogs should be comprehensive.
    """
    return asyncio.run(
        discover_packages(
            keywords,
            search_queries=queries,
            max_per_source=max_per_source,
        )
    )


def cmd_generate(args: argparse.Namespace) -> None:
    """Generate a single domain catalog."""
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    extra_queries = None
    if args.queries:
        extra_queries = [q.strip() for q in args.queries.split(",") if q.strip()]

    # Expand queries for comprehensive catalog generation
    queries = _expand_queries(keywords, extra_queries)

    display_name = args.display_name or args.domain.replace("_", " ").title()
    description = args.description or f"Package catalog for {display_name}."
    max_per = args.max_per_source

    print(f"Running expanded discovery for domain '{args.domain}'...")
    print(f"  Keywords:        {keywords}")
    print(f"  Queries:         {len(queries)} generated")
    print(f"  Max per source:  {max_per}")

    packages = _run_discovery(keywords, queries, max_per_source=max_per)
    print(f"  Found {len(packages)} packages")

    catalog = _build_catalog_dict(
        domain=args.domain,
        display_name=display_name,
        description=description,
        keywords=keywords,
        packages=packages,
    )

    output = json.dumps(catalog, indent=2, ensure_ascii=False)

    if args.dry_run:
        print("\n--- DRY RUN (not writing) ---")
        print(output)
        return

    out_path = _CATALOG_DIR / f"{args.domain}.json"
    out_path.write_text(output, encoding="utf-8")
    print(f"  Written to {out_path}")

    errors = validate_catalog(out_path)
    if errors:
        print(f"  WARNING — validation errors:")
        for e in errors:
            print(f"    • {e}")
    else:
        print("  Validation passed ✓")


def cmd_regenerate_all(args: argparse.Namespace) -> None:
    """Regenerate all existing catalogs from their stored keywords."""
    catalog_files = sorted(_CATALOG_DIR.glob("*.json"))
    if not catalog_files:
        print("No existing catalogs found.")
        return

    for path in catalog_files:
        print(f"\n{'='*60}")
        print(f"Regenerating: {path.name}")
        data = json.loads(path.read_text(encoding="utf-8"))

        keywords = data.get("keywords", [])
        display_name = data.get("display_name", path.stem)
        description = data.get("description", "")

        if not keywords:
            print(f"  SKIP — no keywords stored in {path.name}")
            continue

        print(f"  Keywords: {keywords}")
        queries = _expand_queries(keywords)
        print(f"  Queries:  {len(queries)} generated")
        packages = _run_discovery(
            keywords, queries, max_per_source=args.max_per_source,
        )
        print(f"  Found {len(packages)} packages")

        catalog = _build_catalog_dict(
            domain=data["domain"],
            display_name=display_name,
            description=description,
            keywords=keywords,
            packages=packages,
        )

        output = json.dumps(catalog, indent=2, ensure_ascii=False)

        if args.dry_run:
            print("  DRY RUN — not writing")
            continue

        path.write_text(output, encoding="utf-8")
        print(f"  Updated {path.name}")


def cmd_validate(args: argparse.Namespace) -> None:
    """Validate a catalog JSON file."""
    path = Path(args.validate)
    errors = validate_catalog(path)
    if errors:
        print(f"Validation FAILED for {path}:")
        for e in errors:
            print(f"  • {e}")
        sys.exit(1)
    else:
        print(f"Validation passed for {path} ✓")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate or manage domain package catalogs."
    )
    parser.add_argument(
        "--domain",
        help="Domain slug (e.g. 'electrophysiology'). Used as filename.",
    )
    parser.add_argument(
        "--keywords",
        help="Comma-separated list of discovery keywords.",
    )
    parser.add_argument(
        "--queries",
        help="Comma-separated list of targeted search phrases for Google CSE.",
    )
    parser.add_argument(
        "--display-name",
        help="Human-friendly domain name (default: titlecased slug).",
    )
    parser.add_argument(
        "--description",
        help="One-line description of the domain catalog.",
    )
    parser.add_argument(
        "--max-per-source",
        type=int,
        default=50,
        help="Max results per discovery source (default: 50, wizard uses 20).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Regenerate ALL existing catalogs from their stored keywords.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview output without writing files.",
    )
    parser.add_argument(
        "--validate",
        metavar="FILE",
        help="Validate an existing catalog JSON file and exit.",
    )

    args = parser.parse_args()

    if args.validate:
        cmd_validate(args)
    elif args.all:
        cmd_regenerate_all(args)
    elif args.domain and args.keywords:
        cmd_generate(args)
    else:
        parser.print_help()
        print(
            "\nExamples:\n"
            '  python scripts/generate_domain_catalog.py --domain test --keywords "test,example"\n'
            "  python scripts/generate_domain_catalog.py --all\n"
            '  python scripts/generate_domain_catalog.py --validate catalog.json\n'
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

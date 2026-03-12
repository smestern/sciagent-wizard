"""
sciagent_wizard.sources — Multi-source scientific software discovery.

Search peer-reviewed databases for domain-relevant software and rank
results into a unified list of ``PackageCandidate`` objects.
"""

from .pypi import search_pypi
from .biotools import search_biotools
from .papers_with_code import search_papers_with_code
from .pubmed import search_pubmed
from .google_cse import search_google_cse
from .ranker import rank_and_deduplicate, discover_packages
from .domain_catalogs import list_catalogs, load_catalog, validate_catalog

__all__ = [
    "search_pypi",
    "search_biotools",
    "search_papers_with_code",
    "search_pubmed",
    "search_google_cse",
    "rank_and_deduplicate",
    "discover_packages",
    "list_catalogs",
    "load_catalog",
    "validate_catalog",
]

"""Ingestion package for Research OS."""

from .parser import (
    deduplicate_papers,
    load_paper_fixtures,
    normalize_title,
    parse_paper_file,
)

__all__ = [
    "parse_paper_file",
    "deduplicate_papers",
    "load_paper_fixtures",
    "normalize_title",
]

"""Google Scholar & OpenAlex Harvester with polite backoff and fallback."""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any, Optional

from research_os.schemas.paper import PaperMetadata

logger = logging.getLogger(__name__)


def reconstruct_abstract_from_inverted_index(inverted_index: Optional[dict[str, list[int]]]) -> str:
    """Reconstruct continuous abstract string from OpenAlex abstract_inverted_index."""
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort(key=lambda x: x[0])
    return " ".join(word for _, word in word_positions)


class ScholarHarvesterClient:
    """Client querying Google Scholar via scholarly with backoff and automatic OpenAlex API fallback."""

    def __init__(self, polite_delay_seconds: float = 1.0, user_agent: str = "ResearchOS/1.0 (mailto:research-os@antigravity.internal)"):
        self.polite_delay_seconds = polite_delay_seconds
        self.user_agent = user_agent
        self._scholarly_available = False
        try:
            from scholarly import scholarly  # type: ignore
            self._scholarly = scholarly
            self._scholarly_available = True
        except ImportError:
            self._scholarly = None

    def search(
        self,
        query: str,
        max_results: int = 10,
        authors: Optional[list[str]] = None,
        prefer_openalex: bool = False,
    ) -> list[PaperMetadata]:
        """Search papers via Google Scholar (with backoff) or fallback to OpenAlex."""
        if not prefer_openalex and self._scholarly_available:
            try:
                results = self._search_scholarly(query, max_results=max_results, authors=authors)
                if results:
                    return results
            except Exception as err:
                logger.warning(f"scholarly query failed ({err}); falling back to OpenAlex API.")

        return self.search_openalex(query=query, max_results=max_results, authors=authors)

    def _search_scholarly(
        self,
        query: str,
        max_results: int = 10,
        authors: Optional[list[str]] = None,
    ) -> list[PaperMetadata]:
        """Execute query using scholarly package with polite delay."""
        full_query = query
        if authors:
            full_query += " " + " ".join(authors)

        search_query = self._scholarly.search_pubs(full_query)
        papers: list[PaperMetadata] = []
        count = 0

        for pub in search_query:
            if count >= max_results:
                break
            time.sleep(self.polite_delay_seconds)
            bib = pub.get("bib", {})
            title = bib.get("title", "Untitled")
            pub_year = None
            if bib.get("pub_year"):
                try:
                    pub_year = int(bib.get("pub_year"))
                except (ValueError, TypeError):
                    pass

            author_names = bib.get("author", [])
            if isinstance(author_names, str):
                author_names = [a.strip() for a in author_names.split(" and ")]

            num_citations = pub.get("num_citations")
            pub_url = pub.get("pub_url")
            paper_id = f"gs_{hash(title) & 0xFFFFFFFF:08x}"

            papers.append(
                PaperMetadata(
                    paper_id=paper_id,
                    title=title,
                    authors=author_names,
                    abstract=bib.get("abstract", ""),
                    year=pub_year,
                    venue=bib.get("venue"),
                    url=pub_url,
                    citation_count=num_citations,
                )
            )
            count += 1

        return papers

    def search_openalex(
        self,
        query: str,
        max_results: int = 10,
        authors: Optional[list[str]] = None,
    ) -> list[PaperMetadata]:
        """Query OpenAlex API works endpoint with polite headers and pagination."""
        params = {
            "search": query,
            "per_page": min(max_results, 50),
            "sort": "relevance_score:desc",
        }
        if authors:
            params["search"] = f"{query} {' '.join(authors)}"

        encoded = urllib.parse.urlencode(params)
        url = f"https://api.openalex.org/works?{encoded}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )

        papers: list[PaperMetadata] = []
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                if response.status == 200:
                    payload = json.loads(response.read().decode("utf-8"))
                    results = payload.get("results", [])
                    for item in results[:max_results]:
                        paper = self._openalex_to_metadata(item)
                        papers.append(paper)
        except Exception as err:
            logger.warning(f"OpenAlex query failed: {err}")

        return papers

    def search_authors_openalex(self, name_query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search authors on OpenAlex to inspect h-index, citations, and institutions."""
        params = {
            "search": name_query,
            "per_page": limit,
        }
        encoded = urllib.parse.urlencode(params)
        url = f"https://api.openalex.org/authors?{encoded}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    results = data.get("results", [])
                    authors = []
                    for a in results:
                        summary_stats = a.get("summary_stats", {})
                        authors.append({
                            "id": a.get("id"),
                            "display_name": a.get("display_name"),
                            "works_count": a.get("works_count", 0),
                            "cited_by_count": a.get("cited_by_count", 0),
                            "h_index": summary_stats.get("h_index", 0),
                            "i10_index": summary_stats.get("i10_index", 0),
                            "2yr_mean_citedness": summary_stats.get("2yr_mean_citedness", 0.0),
                            "affiliations": [
                                aff.get("institution", {}).get("display_name")
                                for aff in a.get("affiliations", [])
                                if aff.get("institution")
                            ],
                        })
                    return authors
        except Exception as err:
            logger.warning(f"OpenAlex author search failed: {err}")
        return []

    def _openalex_to_metadata(self, item: dict[str, Any]) -> PaperMetadata:
        """Convert OpenAlex work dictionary to typed PaperMetadata."""
        openalex_id = item.get("id", "").split("/")[-1] or f"oa_{hash(item.get('title')) & 0xFFFFFFFF:08x}"
        paper_id = f"openalex_{openalex_id}"

        authors = []
        for authorship in item.get("authorships", []):
            author_obj = authorship.get("author", {})
            name = author_obj.get("display_name")
            if name:
                authors.append(name)

        abstract = reconstruct_abstract_from_inverted_index(item.get("abstract_inverted_index"))
        primary_location = item.get("primary_location") or {}
        source = primary_location.get("source") or {}
        venue = source.get("display_name")

        url = primary_location.get("landing_page_url") or primary_location.get("pdf_url") or item.get("doi")

        return PaperMetadata(
            paper_id=paper_id,
            title=item.get("display_name") or item.get("title") or "Untitled Work",
            authors=authors,
            abstract=abstract,
            year=item.get("publication_year"),
            venue=venue,
            doi=item.get("doi"),
            url=url,
            citation_count=item.get("cited_by_count"),
        )

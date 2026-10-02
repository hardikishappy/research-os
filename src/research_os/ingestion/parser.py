"""Corpus ingestion, parsing, and deduplication module for Research OS."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional, Union

try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

from research_os.schemas.paper import (
    ExtractedEquation,
    PaperExtraction,
    PaperMetadata,
    SectionProvenance,
)
from research_os.verify.deterministic import compute_file_sha256


def normalize_title(title: str) -> str:
    """Normalize a title string for deterministic deduplication."""
    cleaned = re.sub(r"[^\w\s]", "", title.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_markdown_or_text(content: str, source_path: Path, checksum: str) -> PaperExtraction:
    """Deterministically parse markdown or structured text into a PaperExtraction artifact."""
    lines = content.splitlines()
    
    title = source_path.stem.replace("_", " ").title()
    authors: list[str] = []
    abstract = ""
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    
    sections: dict[str, str] = {}
    provenances: list[SectionProvenance] = []
    equations: list[ExtractedEquation] = []
    algorithms: list[str] = []
    key_findings: list[str] = []
    limitations: list[str] = []
    
    current_section = "Preamble"
    current_lines: list[str] = []
    section_idx = 0

    # Look for frontmatter or headers
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check for title
        if stripped.startswith("# ") and title == source_path.stem.replace("_", " ").title():
            title = stripped[2:].strip()
            i += 1
            continue

        # Check for metadata tags (e.g. Authors: ..., Year: ...)
        if stripped.lower().startswith("authors:"):
            authors = [a.strip() for a in stripped[8:].split(",") if a.strip()]
            i += 1
            continue
        elif stripped.lower().startswith("year:"):
            try:
                year = int(re.search(r"\d{4}", stripped).group(0))
            except Exception:
                pass
            i += 1
            continue
        elif stripped.lower().startswith("venue:"):
            venue = stripped[6:].strip()
            i += 1
            continue
        elif stripped.lower().startswith("doi:"):
            doi = stripped[4:].strip()
            i += 1
            continue
        elif stripped.lower().startswith("arxiv:"):
            arxiv_id = stripped[6:].strip()
            i += 1
            continue

        # Check for section headers (## Heading)
        if re.match(r"^#{1,3}\s+[A-Za-z0-9]", stripped):
            # Save previous section
            if current_lines:
                sec_text = "\n".join(current_lines).strip()
                if current_section.lower() == "abstract":
                    abstract = sec_text
                elif sec_text and current_section != "Preamble":
                    sections[current_section] = sec_text
                    provenances.append(
                        SectionProvenance(
                            source_paper_id="",  # filled below
                            section_title=current_section,
                            section_index=section_idx,
                            page_start=1,
                            page_end=1,
                            text_snippet=sec_text[:300],
                        )
                    )
                    section_idx += 1
                current_lines = []

            current_section = re.sub(r"^#{1,3}\s+", "", stripped)
            i += 1
            continue

        # Extract LaTeX equations ($$ ... $$)
        if stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) > 4:
            eq_latex = stripped[2:-2].strip()
            eq_id = f"eq_{len(equations) + 1}"
            equations.append(
                ExtractedEquation(
                    equation_id=eq_id,
                    latex=eq_latex,
                    description=f"Formula in {current_section}",
                    provenance=SectionProvenance(
                        source_paper_id="",
                        section_title=current_section,
                        section_index=section_idx,
                        page_start=1,
                        page_end=1,
                        text_snippet=stripped,
                    ),
                )
            )

        # Extract findings / limitations
        if stripped.lower().startswith(("- finding:", "* finding:", "- result:", "* result:")):
            key_findings.append(re.sub(r"^[-*]\s*(finding|result):\s*", "", stripped, flags=re.IGNORECASE))
        elif stripped.lower().startswith(("- limitation:", "* limitation:", "- constraint:", "* constraint:")):
            limitations.append(re.sub(r"^[-*]\s*(limitation|constraint):\s*", "", stripped, flags=re.IGNORECASE))
        elif stripped.lower().startswith(("- algorithm:", "* algorithm:")):
            algorithms.append(re.sub(r"^[-*]\s*algorithm:\s*", "", stripped, flags=re.IGNORECASE))

        current_lines.append(line)
        i += 1

    # Save final section
    if current_lines:
        sec_text = "\n".join(current_lines).strip()
        if current_section.lower() == "abstract":
            abstract = sec_text
        elif sec_text and current_section != "Preamble":
            sections[current_section] = sec_text
            provenances.append(
                SectionProvenance(
                    source_paper_id="",
                    section_title=current_section,
                    section_index=section_idx,
                    page_start=1,
                    page_end=1,
                    text_snippet=sec_text[:300],
                )
            )

    # Deterministic Paper ID
    raw_id_material = f"{doi or ''}:{arxiv_id or ''}:{normalize_title(title)}"
    paper_id = f"paper-{hashlib.sha256(raw_id_material.encode('utf-8')).hexdigest()[:12]}"
    extraction_id = f"ext-{hashlib.sha256((paper_id + checksum).encode('utf-8')).hexdigest()[:12]}"

    # Backfill source_paper_id into provenances
    for prov in provenances:
        prov.source_paper_id = paper_id
    for eq in equations:
        eq.provenance.source_paper_id = paper_id

    metadata = PaperMetadata(
        paper_id=paper_id,
        title=title,
        authors=authors if authors else ["Unknown Author"],
        abstract=abstract,
        year=year,
        venue=venue,
        doi=doi,
        arxiv_id=arxiv_id,
        url=f"file:///{source_path.as_posix()}",
    )

    return PaperExtraction(
        extraction_id=extraction_id,
        paper_id=paper_id,
        metadata=metadata,
        sections=sections,
        section_provenance=provenances,
        equations=equations,
        algorithms=algorithms,
        key_findings=key_findings,
        limitations=limitations,
        source_checksum=checksum,
    )


def parse_pdf_file(source_path: Path, checksum: str) -> PaperExtraction:
    """Deterministically parse a PDF document using pypdf into a PaperExtraction artifact."""
    if not PYPDF_AVAILABLE:
        raise RuntimeError("pypdf is required to parse PDF files. Install it with pip install pypdf.")

    reader = pypdf.PdfReader(str(source_path))
    pages_text: list[tuple[int, str]] = []
    full_text_list: list[str] = []

    for idx, page in enumerate(reader.pages, start=1):
        txt = page.extract_text() or ""
        pages_text.append((idx, txt))
        full_text_list.append(txt)

    combined_text = "\n\n".join(full_text_list)
    # Parse the extracted text as structured document
    extraction = parse_markdown_or_text(combined_text, source_path, checksum)

    # Correct page numbers in provenance based on where section texts appear
    for prov in extraction.section_provenance:
        target_snippet = prov.text_snippet[:100]
        for page_num, ptext in pages_text:
            if target_snippet in ptext:
                prov.page_start = page_num
                prov.page_end = page_num
                break

    return extraction


def parse_paper_file(file_path: Union[str, Path]) -> PaperExtraction:
    """Parse any supported paper file (JSON, Markdown, TXT, or PDF) into a PaperExtraction."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Paper file does not exist: {path}")

    checksum = compute_file_sha256(path)
    suffix = path.suffix.lower()

    if suffix == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # If it's already a full PaperExtraction JSON
        if "extraction_id" in data and "paper_id" in data and "metadata" in data:
            return PaperExtraction.model_validate(data)
        # Otherwise if it's raw paper dict with title/abstract/sections
        content = json.dumps(data)
        return parse_markdown_or_text(content, path, checksum)

    elif suffix in (".md", ".txt"):
        content = path.read_text(encoding="utf-8", errors="replace")
        return parse_markdown_or_text(content, path, checksum)

    elif suffix == ".pdf":
        return parse_pdf_file(path, checksum)

    else:
        raise ValueError(f"Unsupported file format: {suffix}. Supported: .json, .md, .txt, .pdf")


def deduplicate_papers(papers: list[PaperExtraction]) -> list[PaperExtraction]:
    """Deterministically deduplicate a list of parsed papers.

    Deduplication precedence:
    1. Matching non-null DOI.
    2. Matching non-null arXiv ID.
    3. Normalized title.
    4. Exact source checksum.
    """
    seen_dois: set[str] = set()
    seen_arxiv: set[str] = set()
    seen_titles: set[str] = set()
    seen_checksums: set[str] = set()

    unique_papers: list[PaperExtraction] = []

    for paper in sorted(papers, key=lambda p: p.paper_id):
        # 1. DOI check
        doi = paper.metadata.doi.lower().strip() if paper.metadata.doi else None
        if doi and doi in seen_dois:
            continue

        # 2. arXiv check
        arxiv = paper.metadata.arxiv_id.lower().strip() if paper.metadata.arxiv_id else None
        if arxiv and arxiv in seen_arxiv:
            continue

        # 3. Normalized title check
        norm_title = normalize_title(paper.metadata.title)
        if norm_title and norm_title in seen_titles:
            continue

        # 4. Checksum check
        if paper.source_checksum in seen_checksums:
            continue

        if doi:
            seen_dois.add(doi)
        if arxiv:
            seen_arxiv.add(arxiv)
        if norm_title:
            seen_titles.add(norm_title)
        seen_checksums.add(paper.source_checksum)

        unique_papers.append(paper)

    return unique_papers


def load_paper_fixtures(dir_path: Union[str, Path]) -> list[PaperExtraction]:
    """Load, parse, and deduplicate all paper files from a directory."""
    path = Path(dir_path)
    if not path.is_dir():
        raise NotADirectoryError(f"Directory not found: {path}")

    supported_suffixes = {".json", ".md", ".txt", ".pdf"}
    raw_papers: list[PaperExtraction] = []

    for file_path in sorted(path.rglob("*")):
        if file_path.is_file() and file_path.suffix.lower() in supported_suffixes:
            extraction = parse_paper_file(file_path)
            raw_papers.append(extraction)

    return deduplicate_papers(raw_papers)

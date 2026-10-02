# License and Intellectual Property Audit

This audit evaluates the intellectual property (IP), software licenses, dependency constraints, and legal/architectural risks associated with integrating or referencing the five target source repositories within **Research OS**.

---

## 1. Summary Audit Table

| Repository | Upstream Owner | License Type | Commercial Use Allowed? | Modification & Distribution Allowed? | Attribution Requirements | Architectural Risk Level | Final Recommendation |
| :--- | :--- | :--- | :---: | :---: | :--- | :---: | :--- |
| **SciPIP** | `cheerss` | **MIT** | Yes | Yes | Retain copyright notice & license text | **HIGH** (Neo4j GPL/commercial licensing, Cypher injection, JVM binaries) | **SAFER TO REIMPLEMENT INDEPENDENTLY** |
| **research_assistant** | `mshumer` | **MIT** | Yes | Yes | Retain copyright notice & license text | **HIGH** (Security vulnerability: `eval()`, proprietary API lock-in) | **SAFER TO REIMPLEMENT INDEPENDENTLY** |
| **Paper2Code** | `issol14` | **MIT** | Yes | Yes | Retain copyright notice & license text | **LOW** (Unexecutable markdown skill instructions) | **REIMPLEMENT & FORMALIZE INDEPENDENTLY** |
| **Polaris** | `ZJU-REAL` | **Apache 2.0** | Yes | Yes | Retain NOTICE file, state changes, preserve patent grant | **MEDIUM** (Monorepo complexity, Cordis/Node kernel + FastAPI stack) | **REFERENCE ARCHITECTURE; REIMPLEMENT CORE ENGINE** |
| **PaperGym** | `yunjoochoi` | **MIT** | Yes | Yes | Retain copyright notice & license text | **LOW-MEDIUM** (POSIX `fcntl` Windows incompatibility, Docker dependency) | **REIMPLEMENT SEED PIPELINE WITH TYPED SCHEMAS** |

---

## 2. Granular Repository Analysis

### 2.1 SciPIP
- **Repository URL**: `https://github.com/cheerss/SciPIP`
- **Declared License**: MIT License (Copyright (c) 2024 cheerss)
- **External & Transitive Licenses**:
  - **Neo4j Community Edition**: Licensed under **GPLv3** with Free FLOSS exception. Embedding Neo4j directly or coupling deeply creates copyleft infection risks unless Neo4j is strictly treated as an external, network-isolated daemon or replaced with an embedded database.
  - **GROBID & PDFFigures2**: GROBID is Apache 2.0; PDFFigures2 is Apache 2.0. The repository bundles a precompiled Scala/Java binary JAR: [`pdffigures2-assembly-0.0.12-bin.jar`](file:///references/scipip/src/utils/scipdf/pdf/pdffigures2/pdffigures2-assembly-0.0.12-bin.jar), introducing binary provenance ambiguity and runtime JDK 17 requirements.
- **Attribution & Modification Constraints**: Standard MIT notice required if code is copied.
- **Architectural & Security Risks**:
  - Code contains direct string interpolation into Cypher queries ([`paper_client.py:L61-63`](file:///references/scipip/src/utils/paper_client.py#L61-L63)), creating Cypher injection vulnerabilities.
  - Untyped python dictionaries throughout the entire codebase.
- **Decision**: **SAFER TO REIMPLEMENT INDEPENDENTLY**. Reimplement the core conceptual graph relationships (`Paper`, `Entity`, `CITES`, `RELATED_TO`) using typed Pydantic models on SQLite/PostgreSQL with pgvector, discarding the fragile Neo4j/GROBID/Java pipeline entirely.

---

### 2.2 research_assistant (mshumer / OpenDeepResearcher / ai-researcher)
- **Repository URL**: `https://github.com/mshumer/ai-researcher` and `https://github.com/mshumer/OpenDeepResearcher`
- **Declared License**: MIT License (Copyright (c) 2025 mshumer)
- **External & Transitive Licenses**: Relies on third-party commercial web SaaS services:
  - SerpAPI (Google Search scraping API - commercial terms of service)
  - Jina Reader API (`r.jina.ai` - commercial rate limits)
  - OpenRouter (commercial aggregator)
- **Attribution & Modification Constraints**: Standard MIT notice required if code is copied.
- **Architectural & Security Risks**:
  - Critical security vulnerability: In [`open_deep_researcher.ipynb`](file:///references/research_assistant/open_deep_researcher.ipynb), the script executes `eval(cleaned)` directly on arbitrary LLM string outputs to parse search queries. If an untrusted webpage causes the LLM to output malicious Python code, `eval()` executes arbitrary code on the host machine.
  - No modular package structure; exists solely as Colab notebooks with ephemeral in-memory state.
- **Decision**: **SAFER TO REIMPLEMENT INDEPENDENTLY**. The concept of iterative query expansion should be implemented with deterministic JSON schema validation, safe Pydantic parsing (`model_validate_json`), and native academic APIs (Semantic Scholar, OpenAlex, arXiv).

---

### 2.3 Paper2Code
- **Repository URL**: `https://github.com/issol14/paper2code-skill`
- **Declared License**: MIT License (Copyright (c) 2025 issol14)
- **External & Transitive Licenses**: Markdown text only; no third-party library dependencies except recommendation of `pdftotext` (Poppler).
- **Attribution & Modification Constraints**: Standard MIT notice required.
- **Architectural & Security Risks**:
  - The repository contains no runnable code — only Markdown prompt definitions intended for interactive Claude Code sessions.
  - Prompts rely on LLM adherence without programmatic schema enforcement.
- **Decision**: **REIMPLEMENT & FORMALIZE INDEPENDENTLY**. Adopt the 5-section intermediate representation (file structure, components, validation approach, setup, strategy) as our formal typed YAML/Pydantic schema, and write deterministic code generators that enforce validation.

---

### 2.4 Polaris
- **Repository URL**: `https://github.com/ZJU-REAL/Polaris`
- **Declared License**: Apache License 2.0 (Version 2.0, January 2004)
- **External & Transitive Licenses**:
  - Extensive dependency tree across Python (FastAPI, SQLAlchemy, Alembic, Celery, PyMuPDF, pgvector) and TypeScript/Node.js (Cordis, Vue, VitePress, Electron).
  - License compatibility: Apache 2.0 is fully compatible with MIT and commercial use, provided Section 4 compliance is maintained (retention of copyright, patent, trademark notices, and tracking of modified files).
- **Attribution & Modification Constraints**:
  - Must include a copy of the Apache 2.0 license.
  - Any modified files must carry prominent notices stating that the files were changed.
  - Must preserve all copyright, patent, and trademark notices.
- **Architectural & Security Risks**:
  - Polaris is a heavyweight monorepo designed for institutional research labs with multi-user RBAC, Docker Compose clusters, and multi-service orchestration. Directly forking or merging it introduces massive architectural surface area and dual-language maintenance overhead (TypeScript kernel + Python backend).
- **Decision**: **REFERENCE ARCHITECTURE; REIMPLEMENT CORE SUBSYSTEMS**. Extract and independently reimplement the state machine abstraction (`Voyage`), the human gate protocol (`GateRead`, `GateDecision`), the Research Wiki compilation model, and the citation fact-checking logic in clean, modular Python without the surrounding multi-tenant monorepo baggage.

---

### 2.5 PaperGym
- **Repository URL**: `https://github.com/yunjoochoi/PaperGym`
- **Declared License**: MIT License (Copyright (c) 2026 yun)
- **External & Transitive Licenses**:
  - Depends on `faiss-cpu`, `litellm`, and `docker`.
  - Uses `fcntl` in [`store.py:L1`](file:///references/papergym/src/papergym/library/store.py#L1), which is POSIX-only and throws an immediate `ModuleNotFoundError` on Windows systems.
- **Attribution & Modification Constraints**: Standard MIT notice required.
- **Architectural & Security Risks**:
  - Regex-based JSON extraction (`_extract_json` searching for backtick fences) is prone to decoding failures.
  - Unstructured seed dictionaries (`Seed.to_dict()` and `from_dict()`) rather than strict Pydantic models.
- **Decision**: **REIMPLEMENT SEED PIPELINE WITH TYPED SCHEMAS**. Port the `Seed` schema, active tool accumulator (`Read`, `Grep`, `Bash`), and cross-domain synthesizer into Research OS as Pydantic models with cross-platform SQLite/PostgreSQL persistence.

---

## 3. License Compliance Strategy for Research OS

1. **Clean-Room Implementation**: Research OS shall not copy raw implementation files from the references into production source trees. All pipeline logic, schemas, and runners will be authored cleanly in Research OS.
2. **Third-Party Attribution File**: A dedicated `NOTICE.md` or `CREDITS.md` will explicitly credit:
   - ZJU-REAL for Polaris's Voyage execution and human gate concepts (Apache 2.0).
   - issol14 for Paper2Code's structured YAML intermediate representation (MIT).
   - Yunjoo Choi for PaperGym's tool-augmented seed extraction and cross-domain mechanism composition (MIT).
   - cheerss for SciPIP's entity-paper graph ideation formulation (MIT).
   - Matt Shumer for iterative query refinement patterns (MIT).
3. **No Copyleft Contamination**: By avoiding GPL-licensed components (such as Neo4j Community Edition or unverified external scrapers), Research OS maintains complete commercial and operational freedom under MIT / Apache 2.0 licensing.

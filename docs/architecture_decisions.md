# Research OS Architectural Decision Records (ADRs)

This document formally records the architectural decisions for each key subsystem of **Research OS**. Each decision evaluates reference implementations across the five audited repositories and selects one of five formal postures:
- **REUSE**: Ingest directly as an external package or vendored module with minimal modification.
- **WRAP**: Integrate behind a clean, typed Research OS interface adapter.
- **REIMPLEMENT**: Write a clean-room, typed implementation in Research OS adopting the proven architectural pattern.
- **REFERENCE ONLY**: Consult architectural patterns, prompt structures, and workflows without copying code.
- **REJECT**: Explicitly avoid the architectural approach due to technical, security, or legal liabilities.

---

## Subsystem 1: Literature Ingestion & Paper Parsing Engine

- **Candidate Technologies**:
  - SciPIP `scipdf` (Grobid + bundled Scala/Java `pdffigures2` binary JAR)
  - research_assistant Jina reader API (`https://r.jina.ai/`)
  - Paper2Code Poppler `pdftotext -layout` CLI
  - Polaris PyMuPDF parser + citation regex engine
  - PaperGym Dockerized active explorer (`Read`, `Grep`, `Bash`)
- **Formal Decision**: **REIMPLEMENT** (Hybrid Deterministic Extractor)
- **Technical Justification**:
  - SciPIP's dependency on GROBID and a bundled Java 17 JAR ([`pdffigures2-assembly-0.0.12-bin.jar`](file:///references/scipip/src/utils/scipdf/pdf/pdffigures2/pdffigures2-assembly-0.0.12-bin.jar)) violates Research OS's minimal dependency and portability constraints.
  - research_assistant's Jina web scraper cannot parse equations, multi-column tables, or structured academic metadata.
  - Paper2Code's `pdftotext` strips mathematical formatting and table structures.
  - Polaris demonstrates that PyMuPDF (`fitz`) provides fast, deterministic extraction of structured text blocks and layout spans without heavyweight background daemons.
  - Research OS will build a hybrid extractor: PyMuPDF for structural layout and metadata extraction, combined with Marker/Nougat for formula extraction, while WRAPPING PaperGym's tool-augmented inspection for extracting code mechanisms from cloned paper repositories.
- **Actions**:
  - **REJECT**: SciPIP's GROBID / `pdffigures2` dependency.
  - **REJECT**: research_assistant's Jina web scraping approach.
  - **REFERENCE ONLY**: Paper2Code's PDF download CLI routines.
  - **REIMPLEMENT**: Polaris's PyMuPDF block extraction into a typed `PaperDocument` Pydantic model.
  - **WRAP**: PaperGym's active tool inspection for code repo analysis.

---

## Subsystem 2: Knowledge Layer & Literature Representation

- **Candidate Technologies**:
  - SciPIP Neo4j Graph Database (Cypher queries + vector index)
  - research_assistant in-memory string concatenation
  - Paper2Code file-based YAML files
  - Polaris PostgreSQL + pgvector Research Wiki ("Compile don't retrieve")
  - PaperGym FAISS + domain-partitioned `seeds.jsonl`
- **Formal Decision**: **REIMPLEMENT** (Relational Graph Store with Vector Indexing)
- **Technical Justification**:
  - SciPIP's Neo4j dependency incurs significant operational overhead (JVM, dedicated port management, GPLv3 license risks) and contains severe Cypher injection vulnerabilities ([`paper_client.py:L61-63`](file:///references/scipip/src/utils/paper_client.py#L61-L63)).
  - PaperGym's FAISS store relies on POSIX `fcntl` file locking ([`store.py:L1`](file:///references/papergym/src/papergym/library/store.py#L1)), breaking portability on Windows.
  - Polaris's "Compile don't retrieve" architecture is superior: papers are ingested once, compiled into structured wiki articles (TL;DR, methodology, reusable mechanisms, concept backlinks), and stored in PostgreSQL with pgvector embeddings.
  - Research OS will implement a dual-backend storage layer: SQLite + `sqlite-vec` for lightweight single-node developer execution, and PostgreSQL + `pgvector` for production multi-user deployments.
- **Actions**:
  - **REJECT**: SciPIP's Neo4j engine.
  - **REJECT**: PaperGym's `fcntl`-locked FAISS store for production persistence.
  - **REFERENCE ONLY**: SciPIP's graph ontology (`Paper`, `Entity`, `CITES`, `RELATED_TO`).
  - **REIMPLEMENT**: Polaris's Research Wiki schema and pgvector retrieval engine using Pydantic and SQLAlchemy.

---

## Subsystem 3: Ideation & Cross-Domain Recombination Engine

- **Candidate Technologies**:
  - SciPIP multi-step XML prompt pipeline (problem → inspiration → idea → novelty filter)
  - research_assistant iterative search query loop
  - Paper2Code (none; reproduction only)
  - Polaris Idea Forge (multi-signal gap analysis + Elo tournament debate)
  - PaperGym cross-domain mechanism synthesizer (`accumulator` + `paraphraser` + `synthesizer`)
- **Formal Decision**: **REIMPLEMENT** (Provenance-Grounded Recombination Engine)
- **Technical Justification**:
  - SciPIP's ideation relies on brittle XML prompt parsing and string splitting (`**Idea 1`, `**Idea 2`) without structured schemas.
  - PaperGym provides the most principled ideation breakthrough: decomposing papers into discrete `Seed` mechanisms (`problem`, `method`, `domain`) and synthesizing solutions by explicitly paraphrasing queries across multiple domains and recombining borrowed mechanisms.
  - Polaris adds multi-signal gap analysis (concept co-occurrence holes, author-stated limitations, trend velocity).
  - Research OS will synthesize PaperGym's cross-domain mechanism borrowing with Polaris's gap analysis. Every generated idea must produce a strictly typed Pydantic `ResearchHypothesis` that links directly to underlying paper seed IDs.
- **Actions**:
  - **REJECT**: SciPIP's untyped string-splitting ideation logic.
  - **REJECT**: research_assistant's prompt query loop.
  - **REIMPLEMENT**: PaperGym's `Seed` schema and cross-domain mechanism synthesis into typed Pydantic models.
  - **REFERENCE ONLY**: Polaris's gap analysis and Elo debate mechanisms.

---

## Subsystem 4: Structured Research Planning & Intermediate Representation (IR)

- **Candidate Technologies**:
  - Paper2Code 5-section YAML Intermediate Representation
  - Polaris Voyage Step DAG
  - SciPIP (none)
  - PaperGym (none)
- **Formal Decision**: **REIMPLEMENT & FORMALIZE** (Pydantic-Enforced Plan IR)
- **Technical Justification**:
  - Paper2Code demonstrated that attempting to generate research code directly from paper text yields high failure rates, hallucinated APIs, and missing hyperparameter configurations. Its 5-section YAML structure ([`03_code_planning.md`](file:///references/paper2code/skills/paper2code/03_code_planning.md)) bridges the conceptual gap between paper equations and executable code.
  - However, Paper2Code relies on Claude Code reading markdown instructions; it lacks programmatic schema validation.
  - Research OS will formalize Paper2Code's YAML structure into a strict Pydantic model (`ResearchPlanIR`) with deterministic validation:
    1. `file_structure`: Explicit directory and file tree.
    2. `implementation_components`: Model architecture, math equations, and algorithm pseudocode.
    3. `validation_approach`: Synthetic smoke test data, metric bounds, and assertions.
    4. `environment_setup`: Dependencies, hardware constraints, and environment variables.
    5. `execution_dag`: Ordered step progression with human approval gates.
- **Actions**:
  - **REIMPLEMENT & FORMALIZE**: Paper2Code's YAML IR into strict Pydantic schemas.
  - **REFERENCE ONLY**: Paper2Code's Phase 1-3 behavioral guidelines.

---

## Subsystem 5: Code Generation & Scaffolding Engine

- **Candidate Technologies**:
  - Paper2Code single-file iterative generation with behavioral DO/DON'T rules
  - Polaris experiment script generator
- **Formal Decision**: **REIMPLEMENT** (Schema-Constrained Code Synthesizer)
- **Technical Justification**:
  - Paper2Code's behavioral rule — "generate one file at a time, never ask permission between files, test immediately, stick strictly to paper spec" — dramatically reduces hallucination and context exhaustion.
  - Polaris demonstrates how to wire generated code into structured metric loggers (TensorBoard/WandB/JSONL) for automated parsing.
  - Research OS will implement a code generation engine that takes the validated `ResearchPlanIR`, generates code file-by-file into an isolated workspace, and runs deterministic AST syntax checks and linting before execution.
- **Actions**:
  - **REFERENCE ONLY**: Paper2Code's single-file generation rules.
  - **REIMPLEMENT**: Polaris's automated metric logging injection and script scaffolding.

---

## Subsystem 6: Experiment Execution Sandbox & Telemetry Engine

- **Candidate Technologies**:
  - Polaris SSH execution on remote GPU servers with Fernet encryption
  - PaperGym Docker container tool loop
  - Paper2Code interactive bash execution
- **Formal Decision**: **REIMPLEMENT** (Containerized Sandbox with Telemetry Daemon)
- **Technical Justification**:
  - Paper2Code's reliance on un-sandboxed local terminal commands is unacceptable for an autonomous research OS running untrusted generated code.
  - PaperGym demonstrates safe isolation using Docker containers per paper environment.
  - Polaris provides the production model for experiment telemetry: remote execution, live stdout/stderr streaming, metric curve extraction, and auto-repair loops constrained by time budgets rather than retry counts.
  - Research OS will provide an execution abstraction layer:
    - Tier 1: Local Docker container sandbox with CPU/GPU cgroups and network isolation.
    - Tier 2: Remote SSH execution engine (following Polaris's encrypted credential architecture) for GPU clusters.
- **Actions**:
  - **REJECT**: Un-sandboxed host execution.
  - **REIMPLEMENT**: PaperGym's Docker container isolation pattern.
  - **REFERENCE ONLY**: Polaris's SSH execution manager and metric streaming protocol.

---

## Subsystem 7: Verification & Provenance Fact-Checker

- **Candidate Technologies**:
  - Polaris line-by-line citation verification & experiment metric fact-checker
  - PaperGym LLM judge grounding checks
  - SciPIP LLM novelty scoring
- **Formal Decision**: **REIMPLEMENT** (Deterministic Verification Engine)
- **Technical Justification**:
  - SciPIP and PaperGym rely on LLMs to judge whether an idea is novel or grounded. LLM-as-a-judge is non-deterministic, expensive, and susceptible to sycophancy.
  - Polaris implements the gold standard for scientific verification:
    1. **Fact-Checking**: Every metric reported in a generated report or paper is deterministically matched against raw `ExperimentRun` database records. Discrepancies cause hard validation failures.
    2. **Citation Verification**: Every citation is verified for existence (against CrossRef/Semantic Scholar/OpenAlex) and contextual support. Fabricated citations trigger an immediate non-pass.
  - Research OS will implement Polaris's deterministic verification model as a mandatory automated gate prior to human review.
- **Actions**:
  - **REJECT**: Pure LLM-as-a-judge without deterministic ground truth.
  - **REIMPLEMENT**: Polaris's metric fact-checking and citation verification engine in modular Python.

---

## Subsystem 8: Long-Running State Machine & Human Gate Protocol

- **Candidate Technologies**:
  - Polaris Voyage engine & Gate API
  - PaperGym tool loop (`run_tool_loop`)
  - research_assistant iterative while-loop
- **Formal Decision**: **REIMPLEMENT** (Deterministic State Machine with Human-in-the-Loop Gates)
- **Technical Justification**:
  - Autonomous research is inherently long-running (hours to days). Notebook while-loops (research_assistant) or single-session scripts lose state on crash or timeout.
  - Polaris's `Voyage` abstraction ([`schemas/voyage.py`](file:///references/polaris/src/backend/app/schemas/voyage.py)) and `Gate` system ([`schemas/gate.py`](file:///references/polaris/src/backend/app/schemas/gate.py)) represent the most mature architecture:
    - Runs are modeled as persisted state machines with step sequences, attempt counters, and pause/resume capabilities.
    - Transitions between critical stages (e.g., Idea Promotion, Compute Budget Approval, Experiment Execution, Paper Submission) are blocked at explicit human approval gates.
  - Research OS will adopt this exact operational philosophy: every research task is an auditable, resumable Voyage with cryptographically signed Pydantic checkpoints and mandatory human gate approvals.
- **Actions**:
  - **REJECT**: Ephemeral in-memory loops.
  - **REIMPLEMENT**: Polaris's Voyage and Gate schemas into a streamlined, framework-independent Python core.

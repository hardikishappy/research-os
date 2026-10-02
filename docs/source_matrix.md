# Source Repository Capability Matrix

This document provides a comparative capability audit of five reference repositories against the target architectural requirements of **Research OS** — a human-gated AI Research Operating System designed to turn literature into verified research experiments with strict reproducibility and auditable provenance.

## Legend
- `✓` = Directly supported (native first-class feature with functional implementation)
- `~` = Partially supported (heuristic, incomplete, unmaintained, or prototype-level)
- `✗` = Not supported (absent from codebase)
- `?` = Unclear / Unverified (ambiguous documentation without verifying code)

---

## 1. Capability Matrix

| Capability | SciPIP | research_assistant (mshumer) | Paper2Code | Polaris | PaperGym | Research OS (Target) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Paper Search** | `~` | `~` | `~` | `✓` | `~` | `✓` |
| **Paper Extraction** | `~` | `~` | `~` | `✓` | `✓` | `✓` |
| **Paper Comparison** | `~` | `✗` | `✗` | `✓` | `~` | `✓` |
| **Literature Synthesis** | `~` | `~` | `✗` | `✓` | `✓` | `✓` |
| **Knowledge Graph** | `✓` | `✗` | `✗` | `✓` | `~` | `✓` |
| **Idea Generation** | `✓` | `✗` | `✗` | `✓` | `✓` | `✓` |
| **Research Planning** | `✗` | `~` | `✓` | `✓` | `✗` | `✓` |
| **Code Generation** | `✗` | `✗` | `✓` | `✓` | `✗` | `✓` |
| **Experiment Execution**| `✗` | `✗` | `~` | `✓` | `✗` | `✓` |
| **Verification** | `✗` | `✗` | `~` | `✓` | `~` | `✓` |
| **Persistent State** | `~` | `✗` | `~` | `✓` | `~` | `✓` |
| **Evaluation** | `~` | `✗` | `✗` | `✓` | `✓` | `✓` |

---

## 2. Granular Capability Breakdown & Evidence

### 2.1 Paper Search
- **SciPIP (`~`)**: Implements targeted crawling for specific venues (ACL, EMNLP, CVPR) via Hugging Face and Semantic Scholar in [`paper_crawling.py`](file:///references/scipip/src/utils/paper_crawling.py) and [`paper_retriever.py`](file:///references/scipip/src/utils/paper_retriever.py). Lacks general-purpose multi-corpus academic search.
- **research_assistant (`~`)**: Relies on commercial SerpAPI for Google search queries in [`open_deep_researcher.ipynb`](file:///references/research_assistant/open_deep_researcher.ipynb). Does not interface with structured academic repositories (Semantic Scholar, arXiv, OpenAlex, PubMed).
- **Paper2Code (`~`)**: Relies on human input for arXiv URLs or local PDFs; provides optional web/GitHub search instructions in [`05_reference_search.md`](file:///references/paper2code/skills/paper2code/05_reference_search.md).
- **Polaris (`✓`)**: Full production integration with OpenAlex, Semantic Scholar, and arXiv APIs in [`polaris/src/backend/app/services/`](file:///references/polaris/src/backend/app/services/) with watermark-based incremental resumption and daily feed sync.
- **PaperGym (`~`)**: Includes offline bootstrap download scripts for arXiv and Semantic Scholar in [`scripts/sample_envs.py`](file:///references/papergym/scripts/sample_envs.py); lacks dynamic user-facing search interface.
- **Research OS Target (`✓`)**: Deterministic multi-source retrieval (Semantic Scholar, OpenAlex, arXiv, PubMed) with deduplication by DOI/arXiv ID/title hash, rate-limiting, and local caching.

### 2.2 Paper Extraction
- **SciPIP (`~`)**: Wraps `scipdf` using GROBID and a bundled Java binary `pdffigures2` ([`pdffigures2-assembly-0.0.12-bin.jar`](file:///references/scipip/src/utils/scipdf/pdf/pdffigures2/pdffigures2-assembly-0.0.12-bin.jar)). High failure rate on non-standard PDF formats; requires JVM 17+.
- **research_assistant (`~`)**: Pulls web page text via Jina reader API (`https://r.jina.ai/`). Incapable of parsing structured PDF formulas, multi-column layouts, tables, or bibtex citations.
- **Paper2Code (`~`)**: Uses simple Poppler `pdftotext -layout` CLI command ([`SKILL.md`](file:///references/paper2code/skills/paper2code/SKILL.md#L65)). Fails to preserve LaTeX equations, tables, and hierarchical section trees.
- **Polaris (`✓`)**: Robust deterministic PDF processing pipeline using PyMuPDF (fitz), structured text block extraction, figure parsing, and citation regex normalization in [`services/paper.py`](file:///references/polaris/src/backend/app/services/).
- **PaperGym (`✓`)**: Tool-augmented active extraction inside Docker sandbox using `Read`, `Grep`, and `Bash` tools ([`accumulator/agent.py`](file:///references/papergym/src/papergym/agents/accumulator/agent.py)), enabling agents to navigate paper markdown and code repositories dynamically.
- **Research OS Target (`✓`)**: Hybrid deterministic pipeline: PyMuPDF for structural layout and metadata, Nougat/Marker for math and table fidelity, and tool-augmented active inspection in an isolated container.

### 2.3 Paper Comparison
- **SciPIP (`~`)**: Graph-based co-occurrence matching and pairwise LLM similarity scoring using XML prompt [`get_similarity_score.xml`](file:///references/scipip/assets/prompt/get_similarity_score.xml). Lacks structured attribute diffing.
- **research_assistant (`✗`)**: Appends raw search chunks sequentially; no comparative synthesis or structured cross-paper analysis.
- **Paper2Code (`✗`)**: Focused exclusively on single-paper replication.
- **Polaris (`✓`)**: Cross-linked Research Wiki with automated concept backlinks, direction-level relevance scoring, and citation graph exploration.
- **PaperGym (`~`)**: Clusters mechanism seeds into 7 ML domains and computes embedding similarity, but performs comparison implicitly during synthesis.
- **Research OS Target (`✓`)**: Deterministic claim extraction, method diffing, benchmark comparison tables, and concept graph intersection.

### 2.4 Literature Synthesis
- **SciPIP (`~`)**: Concatenates retrieved methodology and intro snippets into LLM prompt [`summarizing.xml`](file:///references/scipip/assets/prompt/summarizing.xml) to draft background summaries.
- **research_assistant (`~`)**: Compiles collected web context into a final markdown narrative report via [`generate_final_report_async`](file:///references/research_assistant/open_deep_researcher.ipynb).
- **Paper2Code (`✗`)**: No multi-paper synthesis capabilities.
- **Polaris (`✓`)**: Shared platform-wide Research Wiki compile engine ("compile once, link everywhere") that synthesizes method, limits, and concept tags into unified persistent wiki entries.
- **PaperGym (`✓`)**: Multi-domain mechanism composition engine that synthesizes a novel methodology explicitly citing borrowed mechanisms (`inspired_by` list).
- **Research OS Target (`✓`)**: Auditable, citation-grounded literature synthesis with strict provenance tracking back to specific paper sections and equations.

### 2.5 Knowledge Graph
- **SciPIP (`✓`)**: First-class Neo4j knowledge graph storing `(:Paper)` and `(:Entity)` nodes with `[:CITES]` and `[:RELATED_TO]` edges ([`paper_client.py`](file:///references/scipip/src/utils/paper_client.py)), combined with Neo4j 5 vector indexes.
- **research_assistant (`✗`)**: No graph storage or relational topology.
- **Paper2Code (`✗`)**: No graph representations.
- **Polaris (`✓`)**: PostgreSQL schema with pgvector embeddings, entity linking, citation trees, and direction libraries in [`schemas/graph.py`](file:///references/polaris/src/backend/app/schemas/graph.py) and [`models/`](file:///references/polaris/src/backend/app/models/).
- **PaperGym (`~`)**: Domain-partitioned FAISS index + `seeds.jsonl` ([`store.py`](file:///references/papergym/src/papergym/library/store.py)); lacks explicit relational graph edges.
- **Research OS Target (`✓`)**: Embedded relational graph store (SQLite with vector extensions or PostgreSQL/pgvector) with deterministic typed entity, paper, method, and claim relations.

### 2.6 Idea Generation
- **SciPIP (`✓`)**: Multi-stage ideation pipeline: Problem Formulation → Inspiration Discovery → Idea Generation → Filtering/Integration ([`generator.py`](file:///references/scipip/src/generator.py)).
- **research_assistant (`✗`)**: Only performs question answering and topical report compilation.
- **Paper2Code (`✗`)**: Focused purely on implementation of existing ideas.
- **Polaris (`✓`)**: Idea Forge multi-signal gap analysis (co-occurrence holes, paper limitations, trend velocity, survey gaps) with Elo tournament review ([`schemas/idea.py`](file:///references/polaris/src/backend/app/schemas/idea.py)).
- **PaperGym (`✓`)**: Domain-paraphrased retrieval across 7 ML domains with cross-mechanism recombination and explicit credit assignment ([`synthesizer/`](file:///references/papergym/src/papergym/agents/synthesizer/)).
- **Research OS Target (`✓`)**: Mechanism-grounded ideation engine combining PaperGym's cross-domain mechanism borrowing with Polaris's gap analysis and strict hypothesis validation.

### 2.7 Research Planning
- **SciPIP (`✗`)**: Generates textual idea descriptions with no implementation breakdown or execution plan.
- **research_assistant (`~`)**: Generates sequential search queries iteratively, but no research or experimental plan.
- **Paper2Code (`✓`)**: State-of-the-art structured YAML planning in [`03_code_planning.md`](file:///references/paper2code/skills/paper2code/03_code_planning.md) specifying file hierarchy, component interfaces, mathematical formulas, hyperparameter mappings, and validation steps.
- **Polaris (`✓`)**: Research Proposal builder with plan-execute-verify loop and step-level Voyage planning ([`schemas/voyage.py`](file:///references/polaris/src/backend/app/schemas/voyage.py)).
- **PaperGym (`✗`)**: Does not produce actionable experimental plans or task DAGs.
- **Research OS Target (`✓`)**: Typed Pydantic Research Plan IR (derived from Paper2Code's YAML structure) with milestone DAGs, compute resource estimates, and human approval checkpoints.

### 2.8 Code Generation
- **SciPIP (`✗`)**: No code generation logic.
- **research_assistant (`✗`)**: No code generation logic.
- **Paper2Code (`✓`)**: Strict single-file iterative code generation rules ([`04_implementation_guide.md`](file:///references/paper2code/skills/paper2code/04_implementation_guide.md)) keeping models, algorithms, and entrypoints aligned with paper specifications.
- **Polaris (`✓`)**: Generates PyTorch/Python experiment scripts, baseline harnesses, and metric logging hooks.
- **PaperGym (`✗`)**: No code generation.
- **Research OS Target (`✓`)**: Schema-driven modular code generation with deterministic linting, type-checking (mypy/pyright), and unit test synthesis before execution.

### 2.9 Experiment Execution
- **SciPIP (`✗`)**: None.
- **research_assistant (`✗`)**: None.
- **Paper2Code (`~`)**: Instructions tell Claude Code to run scripts interactively via bash; lacks automated orchestration or sandboxing.
- **Polaris (`✓`)**: Enterprise SSH execution engine with encrypted credentials, remote GPU server dispatch, live log streaming, metric curves, and auto-iteration under time budgets.
- **PaperGym (`✗`)**: Execution limited to paper reading tools (Read/Grep/Bash) in Docker during seed extraction; does not execute experimental research pipelines.
- **Research OS Target (`✓`)**: Containerized sandbox execution (Docker / local subprocess with resource cgroups) supporting dry runs, smoke tests, metric streaming, and deterministic timeout management.

### 2.10 Verification
- **SciPIP (`✗`)**: LLM-as-a-judge novelty evaluation without deterministic code or claim verification.
- **research_assistant (`✗`)**: Heuristic relevance check ("Yes"/"No" string response).
- **Paper2Code (`~`)**: Self-check question checklists at each phase; no automated test runner.
- **Polaris (`✓`)**: Line-by-line citation verification (existence & support checks) and deterministic fact-checking matching paper numbers directly against `ExperimentRun` database records.
- **PaperGym (`~`)**: Grounding evaluation verifying seeds against cached paper markdown using LLM judge rubrics.
- **Research OS Target (`✓`)**: Multi-tier deterministic verification: AST syntax checks, unit test pass rate, metric threshold assertions, and cryptographic run hashes.

### 2.11 Persistent State
- **SciPIP (`~`)**: Persists papers and embeddings in Neo4j; does not persist agent execution state, ideation sessions, or user runs.
- **research_assistant (`✗`)**: In-memory ephemeral variables in Jupyter notebook.
- **Paper2Code (`~`)**: Writes markdown/YAML intermediate files to project disk.
- **Polaris (`✓`)**: Enterprise Voyage persistence: PostgreSQL + SQLAlchemy + Alembic, state machines, step attempt records, and resumable execution tokens.
- **PaperGym (`~`)**: Writes to `seeds.jsonl` and FAISS index files; uses POSIX `fcntl` file locks.
- **Research OS Target (`✓`)**: Immutable append-only run log in SQLite/PostgreSQL with Pydantic checkpoint serialization, reproducible state transitions, and audit provenance.

### 2.12 Evaluation
- **SciPIP (`~`)**: Script-based retriever evaluation and LLM novelty scoring in [`scripts/retriever_eval.sh`](file:///references/scipip/scripts/retriever_eval.sh) and [`assets/prompt/novelty_eval.xml`](file:///references/scipip/assets/prompt/novelty_eval.xml).
- **research_assistant (`✗`)**: No evaluation suite or benchmarking harness.
- **Paper2Code (`✗`)**: No systematic evaluation suite.
- **Polaris (`✓`)**: Elo tournament debate with multi-persona LLM reviewers and rigorous automated rubric scoring.
- **PaperGym (`✓`)**: Robust benchmark evaluation harness in [`eval/`](file:///references/papergym/eval/) and [`scripts/`](file:///references/papergym/scripts/) with shuffle tests, grounding checks, and multi-condition ablation studies.
- **Research OS Target (`✓`)**: Dual evaluation system: Deterministic metric benchmarking against baseline reference numbers + LLM committee review gated by human sign-off.

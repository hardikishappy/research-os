# Source Repository Deep-Dive: Polaris

- **Repository**: [ZJU-REAL/Polaris](file:///references/polaris)
- **Primary Domain**: Autonomous End-to-End AI Research Platform (Literature to Reviewed Paper)
- **Core Technology Stack**:
  - **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0, Alembic, Celery, PostgreSQL + `pgvector`, PyMuPDF (fitz), Cryptography (Fernet).
  - **Kernel**: TypeScript, Node.js, Cordis plugin framework ([`vendor/deepseek-cordis/`](file:///references/polaris/vendor/deepseek-cordis/)).
  - **Frontend / Desktop**: Vue 3, Vite, CodeMirror 6, Yjs (CRDT), Electron, Tectonic (server-side LaTeX compilation).
- **License**: Apache License 2.0 (Copyright ZJU-REAL)

---

## 1. Core Architecture

Polaris is the most complete and production-hardened reference system audited. It models scientific research as a **six-stage lifecycle** mediated by **human approval gates** and powered by the **Voyage agent core**:

```mermaid
flowchart LR
    L["Literature<br/>(Research Wiki)"] --> I["Idea<br/>(Idea Forge)"]
    I --> R["Idea Review<br/>(Elo Tournament)"]
    R -->|Gate: Promotion| X["Experiment<br/>(GPU via SSH)"]
    X --> W["Paper Writing<br/>(LaTeX / CRDT)"]
    W --> V["Paper Review<br/>(Citation & Fact Check)"]
    V -->|Gate: Submission| S(["Submission"])

    classDef stage fill:#eaf1ff,stroke:#2f6bff,stroke-width:1px;
    classDef gate fill:#fff3e0,stroke:#f59e0b,stroke-width:1px;
    class L,I,R,X,W,V stage;
    class S gate;
```

### The Six Research Stages:
1. **Literature (Research Wiki)**: Ingests from OpenAlex, Semantic Scholar, and arXiv. Adopts the *"Compile don't retrieve"* doctrine: each paper is ingested once and compiled into a structured, platform-wide wiki page (TL;DR, method, reusable ideas, concept backlinks). Concepts are promoted to first-class graph entities once cited by $\ge 2$ papers.
2. **Idea (Idea Forge)**: Multi-signal gap analysis over the knowledge base (concept co-occurrence holes, extracted paper limitations, trend velocity, survey gaps) generates retrieval-planned candidate ideas.
3. **Idea Review**: Configurable-persona reviewer agents debate candidate ideas in pairwise tournaments, producing an Elo ranking. Transitions require a human approval gate.
4. **Experiment (Experiment Lab)**: Connects to GPU servers using per-user, Fernet-encrypted SSH credentials. Plans experiments, performs compute budget checks, writes code, executes smoke tests, and runs training loops with live metric curve streaming. Employs a *time-budget repair loop* rather than a fixed retry counter.
5. **Paper Writing**: Collaborative multi-file LaTeX editor with real-time CRDT and Tectonic PDF rendering. Crucially, *numbers in the paper must be wired to real `ExperimentRun` database metric records*.
6. **Paper Review**: Line-by-line citation verification (existence checked against academic databases; contextual support evaluated) plus deterministic fact-checking of reported numbers against raw experiment logs. A single fabricated citation forces a hard rejection.

---

## 2. Input/Output Schemas & Data Structures

Polaris enforces strict Pydantic models across all subsystems:

### Human Gate Schema ([`src/backend/app/schemas/gate.py`](file:///references/polaris/src/backend/app/schemas/gate.py)):
```python
class GateCreate(BaseModel):
    project_id: uuid.UUID
    kind: str  # idea_promotion | compute_budget | paper_submission | idea_goal | idea_pivot
    payload: dict[str, Any] | None = None
    requested_by: str

class GateDecision(BaseModel):
    comment: str | None = None
    override: bool = False  # Administrator bypass flag

class GateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    status: str  # pending | approved | rejected
    payload: dict[str, Any] | None
    requested_by: str
    decided_by: uuid.UUID | None
    comment: str | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime
```

### Voyage Execution Schema ([`src/backend/app/schemas/voyage.py`](file:///references/polaris/src/backend/app/schemas/voyage.py)):
```python
class VoyageCreate(BaseModel):
    kind: Literal["demo", "discovery", "experiment", "writing"]
    project_id: uuid.UUID
    goal: str = Field(min_length=1)
    params: dict[str, Any] | None = None

class VoyageStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    seq: int              # Immutable creation order
    rank: float = 0.0     # Execution order rank
    attempt: int = 0      # Diagnostic retry count
    title: str
    status: str           # pending | running | paused | blocked | completed | failed
```

---

## 3. Potential Reusability

- **Voyage Agent State Machine**: The core state machine modeling long-running research tasks as resumable, checkpointed, multi-step voyages is the foundational blueprint for Research OS.
- **Human Gate Architecture**: The explicit `Gate` schema pausing runs between critical stages (idea promotion, compute allocation, paper submission) until human sign-off is given.
- **"Compile Don't Retrieve" Wiki**: Pre-compiling papers into structured, persistent wiki pages with concept backlinks eliminates redundant context ingestion and stabilizes retrieval quality.
- **Deterministic Fact-Checking**: The programmatic validation rule requiring every metric in a research report or paper to match an exact database metric record in `ExperimentRun` prevents hallucinated benchmarks.

---

## 4. Weaknesses & Failure Modes

1. **Monorepo Complexity & Stack Bloat**:
   - Polaris is a multi-tier institutional enterprise platform: a TypeScript/Cordis kernel ([`vendor/deepseek-cordis/`](file:///references/polaris/vendor/deepseek-cordis/)), a Python/FastAPI/Celery backend, a Vue 3 web frontend, and an Electron desktop app. Setting up the full environment requires Docker Compose, PostgreSQL + pgvector, Redis, Celery workers, and Node.js.
2. **Infrastructure Barrier**:
   - Experiment execution assumes pre-configured remote Linux GPU servers accessible via SSH credentials. There is no lightweight local container execution runner for single-machine prototyping.
3. **Heavy Dependency Footprint**:
   - Requires Tectonic for LaTeX compilation, Redis for task messaging, and Celery for background scheduling.
4. **Bilingual Kernel/Backend Divide**:
   - Coordination is split between a Node.js Cordis event kernel and a Python FastAPI backend, introducing cross-language serialization complexity.

---

## 5. Architectural Conflicts with Research OS

| Dimension | Polaris Pattern | Research OS Standard | Conflict Resolution |
| :--- | :--- | :--- | :--- |
| **System Footprint** | Multi-service enterprise monorepo | Lean, modular, embeddable Python package | Reimplement core engine in single-process Python |
| **Orchestration** | Dual-stack (TypeScript Cordis + Python) | Unified Python async state machine | Implement pure Python Voyage runner |
| **Local Development**| Heavy Docker Compose + GPU cluster | Local Docker container or subprocess runner | Provide lightweight local runner by default |
| **Database** | Multi-tenant PostgreSQL + pgvector | Dual backend: SQLite (local) / Postgres (prod) | Abstract database behind clean repository layer |

---

## 6. What Research OS Should Do Differently

1. **Lightweight Unified Core**: Extract the brilliant conceptual architecture of Polaris (Voyage state machine, human gates, Research Wiki, fact-checking) and implement it in pure, modern Python (SQLAlchemy + Pydantic v2) without the Node.js/Cordis or Celery dependencies.
2. **Single-Node Execution Sandbox**: Provide an immediate out-of-the-box local Docker runner for experiment execution, allowing developers to run Research OS on a laptop or single workstation without requiring a remote SSH GPU cluster.
3. **Integrate Paper2Code Planning**: Polaris writes experiment scripts directly; integrating Paper2Code's 5-section intermediate representation (IR) into Polaris's experiment voyage will dramatically improve code synthesis accuracy.
4. **Incorporate PaperGym Mechanisms**: Augment Polaris's Idea Forge with PaperGym's tool-augmented active seed extraction and cross-domain mechanism composition.

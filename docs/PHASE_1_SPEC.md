# Phase 1 Specification: Domain Model & State Machine

**Status:** Approved for Execution
**Owner:** Principal Engineer
**Parent Implementation Plan:** [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)

---

## 1. Executive Summary

Phase 1 establishes the "Brain" of the system. We will define the database schema and the `ModelRun` state machine. This is the single source of truth for the entire distributed system.

**Key Definition:** A "Run" is a stateful entity that moves from `PENDING` -> `RUNNING` -> `SUCCEEDED` (or `FAILED`).

## 2. Technical Decisions & Standards

### 2.1 Schema Management

**Decision:** `Alembic`
**Rationale:**

- **Version Control:** All DB changes are versioned code.
- **Reproducibility:** We can recreate the production DB state from scratch in any environment.
- **Safety:** Prevents accidental schema drift.

### 2.2 Data Types

**Decision:**

- `UUID` for primary keys (prevent enumeration attacks, enable client-side ID generation if needed).
- `JSONB` for parameters (flexible schema for different model types).
- `TIMESTAMPTZ` (UTC by default) for all time fields.

### 2.3 ID Generation

**Decision:** `uuid7` (Time-sorted UUIDs) if available, or `uuid4` if not.
**Rationale:** Standard `uuid4` is fine for this scale, but `uuid7` offers better index locality. We will stick to standard `uuid.uuid4()` in Python for broad compatibility in this phase.

---

## 3. Data Model Specification

### 3.1 Enums (`src/domain/schemas.py` or `src/infrastructure/models.py`)

```python
class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
```

### 3.2 Table: `model_runs`

| Column             | Type        | Nullable | Default   | Description                         |
| :----------------- | :---------- | :------- | :-------- | :---------------------------------- |
| `id`               | UUID        | No       | PK        | Unique Run ID                       |
| `status`           | String      | No       | 'PENDING' | State machine status                |
| `parameters`       | JSONB       | No       |           | The input for the model             |
| `payload_hash`     | String      | No       |           | CHA-256 of canonicalized parameters |
| `created_at`       | TIMESTAMPTZ | No       | NOW()     |                                     |
| `started_at`       | TIMESTAMPTZ | Yes      | NULL      | When worker acquired lease          |
| `finished_at`      | TIMESTAMPTZ | Yes      | NULL      | When processing ended               |
| `attempt_count`    | Integer     | No       | 0         | For retry logic                     |
| `lease_owner`      | String      | Yes      | NULL      | ID of worker holding the lease      |
| `lease_expires_at` | TIMESTAMPTZ | Yes      | NULL      | When the lease expires              |
| `result_ref`       | String      | Yes      | NULL      | Path/URI to the output artifact     |
| `last_error`       | Text        | Yes      | NULL      | Human readable error message        |

**Indexes:**

1.  `ix_model_runs_payload_hash` -> On `payload_hash` (For deduplication lookups).
2.  `ix_model_runs_status_lease` -> On `(status, lease_expires_at)` (For finding stale jobs).

---

## 4. Canonicalization Logic (`src/utils.py`)

We need a consistent way to hash JSON inputs so that `{ "a": 1, "b": 2 }` hashes to the same value as `{ "b": 2, "a": 1 }`.

**Algorithm:**

1.  Take input Dictionary.
2.  Serialize to JSON string with:
    - Keys sorted (`sort_keys=True`)
    - No whitespace (`separators=(',', ':')`)
3.  Compute SHA-256 hex digest of the resulting byte string.

---

## 5. Execution Plan (Checklist)

### Step 5.1: Database Migrations Setup

- [ ] Initialize Alembic: `flask db init` or `alembic init` (We will use Alembic directly or via Flask-Migrate if installed, but direct Alembic is cleaner for "Crash-Only" design, let's stick to **Alembic** properly configured in `src/infrastructure/migrations`).
- [ ] Configure `env.py` in Alembic to import our `Base` from `src.infrastructure.database` so it can auto-generate.

### Step 5.2: Domain Models

- [ ] Create `src/infrastructure/models.py`.
- [ ] Define `ModelRun` class inheriting from `Base`.
- [ ] key fields: `id`, `status`, `parameters`, `payload_hash`, `lease_expires_at`.

### Step 5.3: Utility Implementation

- [ ] Create `src/utils.py`.
- [ ] Implement `canonicalize_params(params: dict) -> Tuple[str, str]` (returns json_str, hash).
- [ ] Add unit test for this utility function.

### Step 5.4: Generate Migration

- [ ] Run `alembic revision --autogenerate -m "Initial schema"`.
- [ ] Inspect the generated file.
- [ ] Run `alembic upgrade head`.

### Step 5.5: Verification

- [ ] Connect to DB (via `make shell` or `psql`).
- [ ] Verify table `model_runs` exists with correct columns.

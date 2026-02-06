# Implementation Plan: Model Run Orchestration Service

**Status:** Draft
**Role:** Principal Engineer
**Date:** 2026-02-06
**Target Architecture:** Python/Flask + Postgres + Redis + RQ

---

## 1. Executive Summary & Architecture Analysis

This document outlines the phased implementation strategy for the Model Run Orchestration Service.

### Critical Path Analysis

The core complexity of this system lies not in the computation itself, but in the **state machine correctness** under failure conditions.

- **The "Brain":** Postgres is the single source of truth. The queue (Redis/RQ) is merely a transport mechanism for wake-up signals.
- **The "Lock":** We are simulating distributed locking via Postgres row-level locks (optimistic concurrency control via `WHERE` clauses). This is superior to Redis locks for this use case because the lock state is usually coupled with the transaction that updates the job status.
- **Idempotency:** Essential for determining "exactly-once" delivery semantics from the client's perspective.

### Guiding Principles

1. **DB-First Design:** If it's not in Postgres, it didn't happen.
2. **Crash-Only Software:** We assume any component (Worker, API) can die at any instruction. Recovery is not a special mode; it's the standard startup path.
3. **Observability:** We cannot debug distributed races without correlation IDs and structured logs.

---

## Phase 0: Infrastructure & Scaffolding (Foundation)

**Goal:** Establish a reproducible development environment and database connectivity.

### Tasks

1. **Container Orchestration**:
   - Create `docker-compose.yml` defining:
     - `postgres` (ver 15+)
     - `redis` (ver 7+)
   - Define environment variables file (`.env.example`).
2. **Project Structure**:
   - Initialize Python project (Standard `src/` layout).
   - Setup `SQLAlchemy` (ORM) and `Alembic` (Migrations).
   - Setup `Flask` application factory pattern.
3. **Dependency Management**:
   - define `requirements.txt` / `pyproject.toml` (Flask, SQLAlchemy, psycopg2-binary, redis, rq, structlog).

### Acceptance Criteria

- [ ] `docker-compose up` starts DB and Redis cleanly.
- [ ] Application connects to DB and runs a trivial "SELECT 1".
- [ ] Alembic can auto-generate and apply a dummy migration.

---

## Phase 1: The Domain Model & State Machine

**Goal:** Define the data structures that enforce our invariants.

### Tasks

1. **Canonicalization Utility**:
   - Implement `utils.canonicalize(params: dict) -> (str, str)` returning the compact JSON string and its SHA-256 hash.
   - _Critical:_ Must handle sorting keys and consistent number formatting.
2. **Database Models (`models.py`)**:
   - `ModelRun` model:
     - columns: `id` (UUID), `status` (Enum), `parameters` (JSONB), `payload_hash` (String, Indexed).
     - columns: `lease_owner`, `lease_expires_at`, `result_ref`.
     - Constraints: Index on `(status, lease_expires_at)`.
   - `IdempotencyKey` model (Optional for Phase 1, but models should be planned):
     - `key`, `run_id` (FK).
3. **Migration**:
   - Generate initial schema migration.

### Acceptance Criteria

- [ ] Unit tests prove `canonicalize({'b': 1, 'a': 2}) == canonicalize({'a': 2, 'b': 1})`.
- [ ] DB Schema is deployed to local Postgres.

---

## Phase 2: The API & Idempotency Layer

**Goal:** Allow clients to submit work safely.

### Tasks

1. **API Endpoint: `POST /runs`**:
   - Validation: Ensure `parameters` is valid JSON.
   - Logic:
     1. Canonicalize params -> `payload_hash`.
     2. Check for existing active run (PENDING/RUNNING) with this hash (Deduplication policy).
     3. If exists, return 200 OK + existing `run_id`.
     4. If new, INSERT `ModelRun` within a transaction.
     5. _Post-commit hook:_ Enqueue job token to Redis/RQ.
2. **Read Endpoints**:
   - `GET /runs/{id}`: Return status and metadata.
   - `GET /runs/{id}/result`: Return result if SUCCEEDED.
3. **Idempotency Key Support (Hardening)**:
   - Check `Idempotency-Key` header.
   - Consult `idempotency_keys` table before creating run.

### Acceptance Criteria

- [ ] Sending the same payload twice returns the **same** `run_id`.
- [ ] The `ModelRun` table populates correctly.
- [ ] Redis contains a job message after `POST`.

---

## Phase 3: The Worker & Leasing Engine (The Core)

**Goal:** Implement safe, distributed execution.

### Tasks

1. **Worker Bootstrap**:
   - Setup a custom Worker entrypoint (extending RQ worker or custom script) that initializes the DB context.
2. **Lease Acquisition (The "Atomic CAS")**:
   - Implement the SQL update pattern:
     ```sql
     UPDATE model_runs SET status='RUNNING', lease_owner=me, lease_expire=now+60s
     WHERE id=? AND (status='PENDING' OR (status='RUNNING' AND lease_expire < now))
     ```
   - _Note:_ Do not rely on RQ to guarantee uniqueness. Trust only the DB update row count.
3. **Execution Logic**:
   - If lease acquired: Run "Mock Model" (sleep + random math).
   - If lease failed: Abort (another worker won the race).
4. **Completion**:
   - UPDATE `model_runs` SET status='SUCCEEDED', result_ref=... WHERE id=?
   - Handle exceptions to set status='FAILED' (or retry logic, see Phase 4).

### Acceptance Criteria

- [ ] Start 2 workers. Submit 1 job. Only 1 worker marks it RUNNING.
- [ ] `lease_owner` column correctly reflects the worker ID.

---

## Phase 4: Reliability & Recovery

**Goal:** Handle chaos.

### Tasks

1. **Heartbeating**:
   - inside the model execution loop, spawn a background thread/async task to update `lease_expires_at` every N seconds.
2. **Retry Policy**:
   - Add `attempt_count` logic.
   - On error:
     - If `attempts < MAX`: RESET status to `PENDING`, increment attempt, release lease.
     - If `attempts >= MAX`: SET status `FAILED`.
3. **Recovery ( The "Janitor")**:
   - Create a mechanism (cron or periodic worker check) to find "stuck" jobs (Status=RUNNING but `lease_expires_at` is in the past).
   - This effectively happens automatically if the Lease Acquisition query (Phase 3.2) is written correctly to include `OR (status='RUNNING' AND lease_expire < now)`.

### Acceptance Criteria

- [ ] **The "Kill Test":** Start a long job. Kill the worker process (`kill -9`). Wait for lease expiry. Ensure a second worker picks it up and finishes it.
- [ ] **Retry Test:** Configure model to fail once. Verify `attempt_count` increments and job eventually succeeds.

---

## Phase 5: Observability & Production Readiness

**Goal:** Visibility and operational sanity.

### Tasks

1. **Structured Logging**:
   - Configure `structlog` to output JSON.
   - Inject `run_id` into the logger context for every line in the worker.
2. **Health Checks**:
   - `/healthz` endpoint checking connection to Postgres and Redis.
3. **Artifact Storage**:
   - Implement local filesystem saving for results (`./artifacts/`).
   - Update `result_ref` with the file path.

### Acceptance Criteria

- [ ] Logs show the full lifecycle of a run with a consistent `run_id`.
- [ ] `/healthz` returns 200.

---

## Technical Risks & Mitigations

| Risk                 | Mitigation                                                                                                |
| :------------------- | :-------------------------------------------------------------------------------------------------------- |
| **Zombie Jobs**      | Database leases with expiry (`lease_expires_at`) ensure no job is locked forever if a worker dies.        |
| **Double Execution** | Strict DB constraints and atomic UPDATE ... WHERE clauses prevent two workers from claiming the same run. |
| **Lost Updates**     | All state transitions happen in Postgres. The queue is treated as ephemeral/unreliable.                   |
| **Payload Bloat**    | Hash canonicalization ensures huge JSON bodies don't break deduplication logic.                           |

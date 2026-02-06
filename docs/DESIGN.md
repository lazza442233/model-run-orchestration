# Model Run Orchestration Service (DDIA Practice Project)

**Goal:** Build a production-style backend service that safely orchestrates long-running computations with idempotency, run tracking, leasing, retries, and reproducibility.

**Target stack (aligned with Endgame):**

- **Python** + **Flask** (API)
- **Postgres** (system of record)
- **Redis** (queue + ephemeral locks)
- Worker: **RQ** (recommended) or Celery (optional)
- SQL toolkit: SQLAlchemy (or SQLModel)

---

## 1) Purpose and Motivation

### Why this project exists

This is a mini-version of what modelling/platform companies actually need:

- A user triggers a model run (expensive compute).
- The system cannot block an HTTP request while it runs.
- Users retry requests (network glitches / double clicks).
- Workers crash.
- The system must remain correct under partial failure.
- Results must be reproducible and auditable.

### What “success” looks like

A user can:

1. Submit a model run request (parameters)
2. Immediately receive a stable run id
3. Poll for status
4. Retrieve results
5. Retry safely without creating duplicates
6. See reliable outcomes even if a worker crashes mid-run

---

## 2) DDIA Principles This Project Practices

### Reliability

- Job execution is robust to retries, crashes, timeouts
- Stuck runs are detected and recovered
- Invariants prevent silent corruption

### Correctness (truth you can trust)

- A “run” is a first-class object with explicit lifecycle
- Exactly what inputs produced what outputs is recorded

### Idempotency / Deduplication

- Same request should not create duplicate runs (within a policy)
- Retries of a request are safe

### Transactions and Boundaries

- Creating a run is atomic
- Leasing a run is atomic
- Finalizing a run is atomic

### Observability

- You can answer: What is running? What’s stuck? Why did it fail?

---

## 3) Scope

### In Scope

- API to create runs and read status/results
- Postgres-backed state machine
- Run leasing so only one worker executes a run
- Idempotency via canonical parameter hashing
- Result persistence + artifact referencing
- Retry policy + dead-letter/failure reason
- Metrics/logging (minimal but meaningful)

### Out of Scope (for week 1)

- Multi-tenant auth / RBAC
- Kafka / streaming pipelines
- Complex distributed tracing across multiple services
- Actual heavy model compute (we’ll simulate compute)

---

## 4) Core Concepts and Definitions

### “Run”

A Run is the unit of compute. It includes:

- input parameters
- deterministic payload hash
- status
- timestamps
- attempts
- output location / summary
- error details

### “Snapshot”

For reproducibility, a run should reference an immutable “input snapshot.”

For this project, the snapshot can be:

- a normalized JSON `parameters` blob + `payload_hash`

  Optionally extend later to:

- a separate table for input datasets / versions

### “Lease”

A time-bounded claim by a worker:

- prevents multiple workers from executing the same run
- supports crash recovery

---

## 5) Architecture Overview

### High-level flow

```
Client
  |
  | POST /runs (parameters)
  v
Flask API
  |
  | (TX) insert run + idempotency mapping
  | enqueue job(run_id)
  v
Redis Queue (RQ)
  |
  v
Worker
  |
  | acquire lease (atomic update)
  | execute model
  | persist result
  | finalize status
  v
Postgres
```

### Components

1. **API Service**

- validates input
- canonicalizes parameters
- creates run records transactionally
- enqueues work

1. **Worker**

- claims work via lease
- executes compute
- persists outputs
- retries with backoff

1. **Postgres**

- authoritative source of truth for run state

1. **Redis**

- queue transport (RQ)
- optional ephemeral locks (but DB lease is primary)

---

## 6) Data Model (Postgres)

### Table: `model_runs`

Represents the run state machine.

**Columns**

- `id` UUID PK
- `status` TEXT (or enum)
  - `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`
- `parameters` JSONB NOT NULL (normalized input)
- `payload_hash` TEXT NOT NULL (sha256 of canonicalized params)
- `created_at` TIMESTAMPTZ NOT NULL
- `started_at` TIMESTAMPTZ NULL
- `finished_at` TIMESTAMPTZ NULL
- `attempt_count` INT NOT NULL DEFAULT 0
- `last_error` TEXT NULL
- `result_ref` TEXT NULL (path/key to stored output)
- `lease_owner` TEXT NULL (worker id)
- `lease_expires_at` TIMESTAMPTZ NULL
- `heartbeat_at` TIMESTAMPTZ NULL (optional)

**Indexes**

- `idx_runs_status_created_at` on (status, created_at)
- `idx_runs_payload_hash` on (payload_hash)
- `idx_runs_lease_expires` on (lease_expires_at) where status='RUNNING'

### Table: `idempotency_keys` (optional but recommended)

Maps external idempotency to run id.

- `key` TEXT PK (e.g. client provided)
- `payload_hash` TEXT NOT NULL
- `run_id` UUID NOT NULL FK model_runs(id)
- `created_at` TIMESTAMPTZ NOT NULL
- `expires_at` TIMESTAMPTZ NOT NULL

**Unique policy**

- `UNIQUE(key)`
- Optional: `UNIQUE(payload_hash)` within a TTL window (if you want “same payload returns same run” even without an explicit key)

> Week-1 recommendation: support **both**:
>
> - If client provides `Idempotency-Key`, use it.
> - Otherwise: use payload_hash as best-effort idempotency for a short window (e.g. 10 minutes) OR allow duplicates (your choice — document it).

---

## 7) State Machine Design

### States

- **PENDING**: run created, not yet started
- **RUNNING**: worker has lease, executing
- **SUCCEEDED**: result persisted
- **FAILED**: exhausted retries or fatal error
- **CANCELLED**: user requested cancel (optional)

### Allowed transitions

- PENDING → RUNNING
- RUNNING → SUCCEEDED
- RUNNING → FAILED
- PENDING → CANCELLED
- RUNNING → CANCELLED (optional; may require cooperative cancellation)

### Invariants (must always be true)

1. **A run id is immutable**
2. **A run has exactly one current status**
3. **Only one worker may execute a run at a time**
4. **A run’s payload_hash never changes**
5. **Results are only visible when status=SUCCEEDED**

---

## 8) Idempotency & Canonicalization

### Canonicalization rules

To ensure semantically identical input produces identical hash:

1. Sort keys recursively
2. Ensure consistent numeric formatting (int vs float) if relevant
3. Remove irrelevant fields (timestamps, client metadata) from hashing
4. Serialize to compact JSON

### Payload hash

Compute SHA-256 over canonical JSON string.

**Policy choice**

- If same payload_hash arrives within a short TTL: return existing “most recent non-terminal” run OR return a new run.
- Recommend: return existing run if in PENDING or RUNNING and created within last X mins.

This mimics “prevent duplicate compute” behavior.

---

## 9) Run Leasing (Core Correctness Mechanism)

### Why leasing matters

RQ ensures jobs get executed, but not that:

- only one worker executes the same run
- a worker crash can be recovered safely

The lease makes Postgres the source of truth.

### Lease acquisition algorithm

Worker wants to claim `run_id`:

**Single atomic SQL statement**:

- only succeed if run is claimable:
  - status = PENDING

    OR (status=RUNNING and lease_expires_at < now) // stolen lease

Pseudo-SQL:

```sql
UPDATE model_runs
SET status = 'RUNNING',
    lease_owner = :worker_id,
    lease_expires_at = now() + interval '60 seconds',
    started_at = COALESCE(started_at, now()),
    attempt_count = attempt_count + 1
WHERE id = :run_id
  AND (
        status = 'PENDING'
        OR (status = 'RUNNING' AND lease_expires_at < now())
      )
RETURNING *;
```

If 0 rows returned → worker does nothing (someone else owns it).

### Lease renewal (“heartbeat”)

Long runs need lease extension:

- every 20s, worker updates `lease_expires_at = now() + 60s`, `heartbeat_at = now()`
- if worker dies, lease expires and another worker can recover

---

## 10) Worker Execution Model

### “Model” function

For practice, implement a fake model:

- sleep for N seconds
- produce JSON output with summary stats
- include random failure injection to test retries

Example output:

```json
{
  "run_id": "...",
  "inputs": {...},
  "metrics": {"runtime_seconds": 12.3, "objective": 0.83},
  "notes": "simulated"
}
```

### Retry policy

Define:

- `MAX_ATTEMPTS = 3`
- exponential backoff: 5s, 20s, 60s
- some errors “fatal” (validation errors), others “retryable” (timeouts)

### Failure handling

On exception:

- record `last_error`
- if attempts < max → set status back to PENDING (or keep RUNNING but release lease) and re-enqueue
- if attempts exhausted → status=FAILED

Recommended finalization:

- Worker never leaves the run stuck in RUNNING without lease expiry.

---

## 11) API Design

### 1) Create run

**POST** `/runs`

Request body:

```json
{
  "model": "baseline_forecast_v1",
  "parameters": {
    "scenario": "high_inflation",
    "horizon_months": 24,
    "region": "AU"
  }
}
```

Headers:

- Optional: `Idempotency-Key: <string>`

Response:

```json
{
  "run_id": "...",
  "status": "PENDING",
  "created_at": "...",
  "payload_hash": "...",
  "links": {
    "self": "/runs/{id}",
    "result": "/runs/{id}/result"
  }
}
```

Behavior:

- if idempotency key exists and seen before:
  - return same run_id if payload_hash matches
  - else return 409 conflict (“key reused with different payload”)

### 2) Get run status

**GET** `/runs/{run_id}`

Response includes:

- status
- started_at / finished_at
- attempts
- error summary (if failed)
- result_ref (if succeeded)

### 3) Get run result

**GET** `/runs/{run_id}/result`

- 200 with JSON result if SUCCEEDED
- 409/425/404 if not ready (choose a consistent semantics)
  - recommend: 409 “run not complete” or 404 for no result yet (document it)

### Optional endpoints (if time)

- `POST /runs/{id}/cancel`
- `GET /runs?status=RUNNING` (admin/operator)

---

## 12) Result Storage Strategy

Week-1 simplest:

- store JSON result directly in Postgres in a `result_json` JSONB column

  OR

- store as file on disk with `result_ref` path

Recommended for realism:

- store results in local `./artifacts/{run_id}.json`
- set `result_ref` to that path

  This mimics S3 keys without needing AWS.

If you want extra realism:

- implement `S3ResultStore` abstraction but use local filesystem.

---

## 13) Observability (Make It Feel Like a Real Platform)

### Structured logs

Every log line includes:

- `run_id`
- `payload_hash`
- `worker_id`
- `status`
- `attempt_count`

### Metrics (minimum viable)

If you can, expose `/metrics` (Prometheus style) or just log counters:

- runs_created_total
- runs_succeeded_total
- runs_failed_total
- run_duration_seconds (histogram if possible)
- queue_lag_seconds (created_at → started_at)
- stuck_runs_detected_total

### Health checks

- `/healthz`:
  - checks DB connectivity
  - checks Redis connectivity

---

## 14) Testing Strategy

### Unit tests (fast)

1. Canonicalization produces stable hash regardless of key order
2. Idempotency key reuse:
   - same key + same payload returns same run
   - same key + different payload returns 409
3. Lease acquisition:
   - first worker succeeds
   - second worker fails while lease valid

### Integration tests (valuable)

1. End-to-end: create run → worker processes → status becomes SUCCEEDED
2. Crash simulation: worker starts then “dies” (don’t renew lease) → another worker steals lease → succeeds
3. Retry: inject failure first attempt, succeed second attempt, status ends SUCCEEDED with attempt_count=2

---

## 15) Week Plan (Execution Roadmap)

### Day 1: Schema + Create Run endpoint

- data model
- canonicalization/hash
- create run transaction
- enqueue job

### Day 2: Worker + leasing

- claim run
- execute fake model
- persist result
- finalize status

### Day 3: Heartbeats + stuck-run recovery

- lease renew
- simulate crash
- steal lease

### Day 4: Idempotency hardening

- add idempotency table + conflict behavior
- TTL cleanup policy

### Day 5: Observability + polish

- structured logs
- health endpoints
- minimal metrics/log counters
- README + design doc cleanup

### Day 6–7: Testing + interview walkthrough

- 3 tests minimum that prove your invariants
- prepare explanation: “what can go wrong and why this stays correct”

---

## 16) Interview Walkthrough Narrative (use this verbatim)

> “This project models the platform layer that sits above long-running modelling workloads. I treated runs as first-class state machines persisted in Postgres, because queues don’t provide correctness guarantees under partial failure.
>
> I added canonical parameter hashing and idempotency keys to avoid duplicate runs from retries.
>
> The worker uses a DB-backed lease so only one worker executes a run at a time, and stale leases can be recovered if a worker dies.
>
> Results are only served when the run is in a terminal state, and the system is observable via run states, timestamps, and structured logs.”

---

## 17) Stretch Goals (only if you finish early)

1. **Outbox for “RunCompleted” event**

- Persist event in same transaction as run completion
- Publish asynchronously (DDIA tie-in to dual-write)

1. **Materialized view / derived table**

- e.g., run summary by model/scenario

1. **ETag / caching for GET /runs/{id}**

- reduce polling overhead

---

# End

If you want, paste your preferred tooling choices (Flask vs FastAPI; RQ vs Celery) and I’ll translate the above into a **file/folder scaffold** (exact modules + responsibilities) so you can start coding immediately without design drift.

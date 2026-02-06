# Phase 3 Specification: Worker & Leasing Engine

**Status:** Approved for Execution
**Owner:** Principal Engineer
**Parent Implementation Plan:** [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)

---

## 1. Executive Summary

Phase 3 implements the distributed worker that consumes jobs from Redis. Crucially, it implements the **"Lease Acquisition"** logic. The worker does not blindly execute tasks; it must first win a database-level lock (lease). This ensures guarantees correctness even if Redis delivers a message twice of if a worker crashes.

**Core Invariant:** Only **one** worker can hold the lease for a `run_id` at any given time.

## 2. Technical Decisions & Standards

### 2.1 Worker Framework

**Decision:** Custom wrapper around `RQ` jobs.
**Rationale:**

- RQ handles the polling loop and process forking.
- We will define a single entrypoint function `execute_run(run_id)` which RQ calls.
- This function acts as the "Transaction Controller" for the run.

### 2.2 Leasing Mechanism

**Decision:** Optimistic Concurrency via `UPDATE ... WHERE`.
**Rationale:**

- We avoid heavy table locks.
- We use a "Compare-And-Swap" (CAS) style SQL statement to claim the run.
- Lease duration: **60 seconds**, requiring a heartbeat mechanism.

### 2.3 Heartbeat Strategy

**Decision:** Background Thread.
**Rationale:**

- The model computation runs in the main thread (blocking).
- A separate `threading.Thread` will run every 20s to extend the lease in Postgres while the main thread works.

---

## 3. Leasing Logic Specification

### 3.1 The "Acquire" Query

To claim a run, the worker attempts to update the status to `RUNNING`.

```sql
UPDATE model_runs
SET
  status = 'RUNNING',
  lease_owner = :worker_id,
  lease_expires_at = NOW() + INTERVAL '60 seconds',
  started_at = COALESCE(started_at, NOW()),
  attempt_count = attempt_count + 1
WHERE
  id = :run_id
  AND (
    status = 'PENDING'
    OR
    (status = 'RUNNING' AND lease_expires_at < NOW()) -- Steal zombie lease
  )
RETURNING id;
```

If this query returns a row, we **won** the lease. If it returns nothing, we lost (or the run is already done).

### 3.2 The "Heartbeat" Query

Periodically called to keep the lease alive.

```sql
UPDATE model_runs
SET lease_expires_at = NOW() + INTERVAL '60 seconds'
WHERE id = :run_id AND lease_owner = :worker_id;
```

---

## 4. Execution Flow (`src/worker.py`)

1.  **RQ receives job**: Calls `execute_run(run_id)`.
2.  **Initialize**: Generate `worker_id` (hostname + pid).
3.  **Acquire Lease**: Run the CAS query.
    - If fail: Log "Lease acquisition failed" and return (ack job).
4.  **Start Heartbeat**: Spawn daemon thread.
5.  **Run Model**: Call specific model logic (simulated sleep + math).
6.  **Persist Result**: Save output to local JSON file.
7.  **Finalize**:
    - Stop Heartbeat.
    - Update DB: `status='SUCCEEDED'`, `result_ref=path`.
8.  **Error Handling**:
    - Catch exceptions.
    - Update DB: `status='FAILED'` (or `PENDING` if retriable), `last_error=ex`.

---

## 5. Execution Plan (Checklist)

### Step 5.1: Worker Infrastructure

- [x] Create `src/worker/` package.
- [x] Create `src/worker/loader.py`: The Logic to execute the SQL locking commands using `SQLAlchemy`.
- [x] Implement `acquire_lease` and `renew_lease` functions.

### Step 5.2: Model Simulation

- [x] Create `src/domain/models/base.py`: Interface for models.
- [x] Create `src/domain/models/mock.py`: Implementation that sleeps N seconds and returns random stats.

### Step 5.3: Main Execution Handler

- [x] Create `src/worker/main.py`: The `execute_run` entrypoint.
- [x] Implement the `HeartbeatThread` class.
- [x] Wire up the Try/Except blocks for lifecycle management.

### Step 5.4: Integration Testing

- [x] Add `worker` service to `docker-compose.yml`.
- [x] **Manual Verification**:
  - Trigger a run.
  - Check DB to see `status='RUNNING'`, `lease_owner=worker-1`.
  - Wait for completion -> `status='SUCCEEDED'`.

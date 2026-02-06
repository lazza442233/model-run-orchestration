# Phase 2 Specification: API & Idempotency Layer

**Status:** Approved for Execution
**Owner:** Principal Engineer
**Parent Implementation Plan:** [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)

---

## 1. Executive Summary

Phase 2 focuses on the "Front Door" of the system. We will implement the Flask API endpoints that allow clients to submit jobs and retrieve status.

**Critical Goal:** A client must be able to safely retry a `POST /runs` request (due to network timeout, etc.) without triggering duplicate computations.

## 2. Technical Decisions & Standards

### 2.1 Request Validation

**Decision:** Manual `Pydantic` Model validation.
**Rationale:**

- Flask 3.x doesn't enforce a validation library.
- We already have `pydantic` installed.
- We will define a `CreateRunRequest` model and validate `request.json` against it manually in the route to keep dependencies low.

### 2.2 Queue Strategy

**Decision:** `Redis Queue (RQ)`
**Rationale:**

- **At-Least-Once:** RQ ensures the message gets to a worker.
- **Separation of Concerns:** The API does not run the model; it only _enqueues_ the intent. The DB remains the authoritative record of the _run_, while RQ is just the _notification_ system.

### 2.3 Idempotency Strategy

We will support **two** layers of protection:

1.  **Explicit (Header-based):** if `Idempotency-Key` header is present, we map that opaque string to a `run_id`.
2.  **Implicit (Hash-based):** If no header is present, we check if a `PENDING` or `RUNNING` run exists with the exact same `payload_hash`. This prevents accidental double-clicks.

---

## 3. Data Model Updates (`src/infrastructure/models.py`)

We need a dedicated table to map client-provided keys to our internal run IDs.

### 3.1 Table: `idempotency_keys` (New)

| Column       | Type        | Nullable | Default | Description                     |
| :----------- | :---------- | :------- | :------ | :------------------------------ |
| `key`        | String      | No       | PK      | Client provided key (e.g. UUID) |
| `run_id`     | UUID        | No       | FK      | Reference to `model_runs.id`    |
| `created_at` | TIMESTAMPTZ | No       | NOW()   |                                 |

**Foreign Key:** `run_id` -> `model_runs.id` (ON DELETE CASCADE)

---

## 4. API Specification

### 4.1 `POST /runs`

**Headers:**

- `Idempotency-Key` (Optional): String

**Body:**

```json
{
  "parameters": {
    "model": "forecast_v1",
    "region": "US"
  }
}
```

**Logic Flow:**

1.  **Validate:** Check if `parameters` is valid JSON.
2.  **Canonicalize:** Compute `payload_hash` of parameters.
3.  **Check Explicit Idempotency:**
    - If header exists: Look up `idempotency_keys`.
    - If found -> Return 200 OK + `run.id`.
4.  **Check Implicit Dedup:**
    - Query `model_runs` for `payload_hash` WHERE status IN ('PENDING', 'RUNNING').
    - If found -> Return 200 OK + `run.id`.
5.  **Create:**
    - Transaction Start:
      - INSERT into `model_runs`.
      - INSERT into `idempotency_keys` (if header present).
    - Transaction Commit.
6.  **Enqueue:**
    - Convert `run.id` to string.
    - `q.enqueue('src.worker.execute_run', run_id)`
    - _Note:_ If enqueue fails, the run exists in DB but won't start. This is acceptable (recoverable by Janitor in Phase 4).
7.  **Respond:** 201 Created.

**Response:**

```json
{
  "id": "uuid...",
  "status": "PENDING",
  "created_at": "iso-8601...",
  "parameters": {...}
}
```

### 4.2 `GET /runs/{run_id}`

**Response:**

```json
{
  "id": "...",
  "status": "...",
  "created_at": "...",
  "started_at": null,
  "finished_at": null,
  "result": null,  # or object if SUCCEEDED
  "error": null
}
```

---

## 5. Execution Plan (Checklist)

### Step 5.1: Schema Update

- [ ] Add `IdempotencyKey` model to `src/infrastructure/models.py`.
- [ ] Run `alembic revision --autogenerate -m "Add idempotency keys"`.
- [ ] Apply migration.

### Step 5.2: RQ Infrastructure

- [ ] Create `src/infrastructure/queue.py`:
  - Function `get_queue() -> Queue`.
  - Function `enqueue_run(run_id: UUID)`.

### Step 5.3: API Implementation (`src/api/runs.py`)

- [ ] Define `CreateRunRequest` Pydantic model.
- [ ] Implement `POST /runs` with the logic defined above.
- [ ] Implement `GET /runs/<id>`.
- [ ] Register Blueprint in `src/app.py`.

### Step 5.4: Test Verification

- [ ] **Integration Test:**
  - Submit Run A.
  - Submit Run A again (ensure same ID returned).
  - Submit Run A with `Idempotency-Key: X`.
  - Submit Run B with `Idempotency-Key: X` (Ensure 409 Conflict or same ID returned depending on policy - simplified: return same ID if payload matches, error if mismatch. For Phase 2, just returning mapped ID is fine).
  - Check Redis: `Queue('default').count` should increase.

---

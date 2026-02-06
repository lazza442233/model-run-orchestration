# Phase 0 Specification: Foundation & Infrastructure

**Status:** Approved for Execution
**Owner:** Principal Engineer
**Parent Implementation Plan:** [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)

---

## 1. Executive Summary

Phase 0 focuses on establishing a "Walking Skeleton" — a tiny implementation of the system that performs a small end-to-end function (in this case, booting up and connecting to services). This phase lays the groundwork for standardizing **configuration**, **logging**, and **service orchestration**.

## 2. Technical Decisions & Standards

### 2.1 Dependency Management

**Decision:** `pip-tools` (`requirements.in` -> `requirements.txt`)
**Rationale:**

- **Reproducibility:** Generates a deterministic lockfile (`requirements.txt`) where all transitive dependencies are pinned.
- **Simplicity:** Easier to manage in Docker builds compared to Poetry for simple service deployments.
- **Security:** Allows easy auditing of installed package versions.

### 2.2 Configuration Strategy

**Decision:** `pydantic-settings` (reading `.env` files)
**Rationale:**

- **Type Safety:** Ensures `PORT` is an `int`, `DB_URL` is a valid string, etc., preventing runtime type errors.
- **Fail-Fast:** The application refuses to start if critical environment variables are missing.
- **12-Factor:** Strict separation of config from code.

### 2.3 Database Connectivity

**Decision:** `SQLAlchemy 2.0` (Core + ORM) + `psycopg` (v3)
**Rationale:**

- **Modern Standards:** SQLAlchemy 2.0 enforces explicit transaction management, preventing implicit commit bugs.
- **Performance:** `psycopg` is a robust, performant PostgreSQL adapter.

### 2.4 Observability (Logging)

**Decision:** `structlog`
**Rationale:**

- **Context:** Allows binding global context (e.g., `run_id`, `worker_id`) to all logs in a thread/request.
- **Format:** Emits human-readable logs in Dev and structured JSON in Prod (for Datadog/CloudWatch/ELK).

---

## 3. Directory Structure Specification

We will strictly adhere to the `src` layout to avoid import side-effects and ensuring packaging validity.

```text
/
├── .env.example             # Template for required env vars
├── .gitignore               # Standard Python/Docker ignores
├── Makefile                 # Developer shortcuts (up, down, test, lint)
├── README.md                # Project documentation
├── docker-compose.yml       # Local development orchestration
├── pyproject.toml           # Tool configuration (Ruff, Pytest)
├── requirements.in          # Top-level dependencies
├── requirements.txt         # Pinned execution environment
└── src/
    ├── __init__.py
    ├── app.py               # Application Factory & WSGI Entrypoint
    ├── config.py            # Pydantic Settings implementation
    ├── infrastructure/      # Adapter layer
    │   ├── __init__.py
    │   ├── database.py      # SQLAlchemy setup & session handling
    │   └── logging.py       # Structlog configuration
    └── api/                 # Route handlers (Placeholders for now)
        ├── __init__.py
        └── health.py        # /healthz endpoint
```

---

## 4. Infrastructure Specification (Docker)

### 4.1 Services

1.  **`postgres`**: Version `15-alpine`
    - Volume: `./data/postgres:/var/lib/postgresql/data` (Persistence)
    - Healthcheck: `pg_isready`
2.  **`redis`**: Version `7-alpine`
    - Volume: `./data/redis:/data`
    - Healthcheck: `redis-cli ping`
3.  **`web`**: Python 3.11-slim
    - Mounts: `./src:/app/src` (Hot Reload)
    - Command: `flask run --host=0.0.0.0`

### 4.2 Network

- All services on a private bridge network `model-net`.

---

## 5. Execution Plan (Checklist)

### Step 5.1: Project Skeleton

- [ ] Initialize git repo (if not present).
- [ ] proper `.gitignore` (Python, Docker, .env).
- [ ] Create directory structure `src/infrastructure`, `src/api` etc.

### Step 5.2: Dependencies

- [ ] Create `requirements.in`:
  ```text
  flask==3.0.*
  pydantic-settings
  sqlalchemy>=2.0
  psycopg[binary]>=3.1
  redis
  rq
  structlog
  gunicorn
  ```
- [ ] Create `pyproject.toml` (Ruff config, Pytest config).

### Step 5.3: Core Infrastructure Code

- [ ] `src/config.py`: Define `Settings` class with `DATABASE_URL` and `REDIS_URL`.
- [ ] `src/infra/logging.py`: Setup `structlog.configure()`.
- [ ] `src/infra/database.py`: Setup `SQLAlchemy` declarative base and connection logic.

### Step 5.4: Application Factory

- [ ] `src/app.py`: `create_app()` function that initializes config, db, logging.
- [ ] `src/api/health.py`: Endpoint checking `SELECT 1` on DB and `PING` on Redis.

### Step 5.5: Orchestration

- [ ] `docker-compose.yml`: Define services.
- [ ] `Makefile`: Add `make up` to run `docker-compose up --build`.

### Step 5.6: Verification

- [ ] Run `make up`.
- [ ] `curl localhost:5000/healthz` -> Returns JSON `{"status": "ok", "db": "ok", "redis": "ok"}`.

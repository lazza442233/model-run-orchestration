import pytest
import uuid
from flask import Flask
from src.app import create_app
from src.infrastructure.database import Session, Base, engine
from src.infrastructure.models import ModelRun, IdempotencyKey
from src.infrastructure.queue import get_queue


@pytest.fixture(scope='module')
def app():
    _app = create_app()
    _app.config.update({"TESTING": True})

    # Create tables for tests
    Base.metadata.create_all(bind=engine)

    yield _app

    # Tear down
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope='function')
def db_session():
    session = Session()
    yield session
    session.rollback()
    Session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


def test_create_run_happy_path(client):
    payload = {"parameters": {"model": "test", "x": 1}}

    # 1. Create Run
    resp = client.post('/runs', json=payload)
    assert resp.status_code == 201
    data = resp.json
    assert data['status'] == 'PENDING'
    run_id = data['id']

    # 2. Verify Redis Enqueue
    q = get_queue()
    assert q.count > 0
    # Note: Checking specific job ID in RQ is tricky in integration tests without a worker,
    # but non-zero count implies success.


def test_implicit_deduplication(client):
    """Sending same payload twice should return same run_id if PENDING."""
    payload = {"parameters": {"unique": "implicit_test"}}

    # First Request
    resp1 = client.post('/runs', json=payload)
    assert resp1.status_code == 201
    id1 = resp1.json['id']

    # Second Request
    resp2 = client.post('/runs', json=payload)
    assert resp2.status_code == 200  # OK, not Created
    id2 = resp2.json['id']

    assert id1 == id2


def test_explicit_idempotency(client):
    """Idempotency-Key header should force return of associated run."""
    key = str(uuid.uuid4())
    payload_a = {"parameters": {"x": "A"}}
    payload_b = {"parameters": {"x": "B"}}  # Different payload

    # 1. Create with Key
    resp1 = client.post('/runs', json=payload_a,
                        headers={"Idempotency-Key": key})
    assert resp1.status_code == 201
    id1 = resp1.json['id']

    # 2. Retry with Same Key (Even if parameters arguably changed, the key takes precedence in our simplified logic)
    # Note: In a stricter system we might return 409 Conflict if payload differs.
    # Our current logic map key -> run_id.
    resp2 = client.post('/runs', json=payload_b,
                        headers={"Idempotency-Key": key})
    assert resp2.status_code == 200
    id2 = resp2.json['id']

    assert id1 == id2

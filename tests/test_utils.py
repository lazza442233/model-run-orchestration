from src.utils import canonicalize_params


def test_canonicalize_params_determinism():
    # Different order same content
    p1 = {"a": 1, "b": 2}
    p2 = {"b": 2, "a": 1}

    json1, hash1 = canonicalize_params(p1)
    json2, hash2 = canonicalize_params(p2)

    assert json1 == json2
    assert hash1 == hash2
    assert json1 == '{"a":1,"b":2}'


def test_canonicalize_nested_determinism():
    p1 = {"config": {"x": 10, "y": 20}, "name": "run1"}
    p2 = {"name": "run1", "config": {"y": 20, "x": 10}}

    json1, hash1 = canonicalize_params(p1)
    json2, hash2 = canonicalize_params(p2)

    assert hash1 == hash2

import json
import hashlib
from typing import Tuple, Any


def canonicalize_params(params: dict[str, Any]) -> Tuple[str, str]:
    """
    Produce a canonical JSON representation and its SHA-256 hash.

    This ensures that:
    1. Keys are sorted.
    2. Whitespace is stripped (separators).
    3. The output is deterministic for the same input dictionary.

    Args:
        params: The input parameters dictionary.

    Returns:
        A tuple containing:
        - The canonical JSON string.
        - The SHA-256 hex digest of that string.
    """
    # sort_keys=True ensures key order determinism
    # separators=(',', ':') removes whitespace for compactness and consistency
    canonical_json = json.dumps(params, sort_keys=True, separators=(',', ':'))

    payload_hash = hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()

    return canonical_json, payload_hash

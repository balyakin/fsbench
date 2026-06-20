"""Deterministic seed helpers."""

import hashlib


def build_run_seed(base_seed: int, task_id: str, agent_name: str, repeat: int) -> int:
    """Builds a deterministic run seed for one matrix cell."""
    payload = f"{base_seed}:{task_id}:{agent_name}:{repeat}"
    payload_bytes = payload.encode("utf-8")
    digest = hashlib.sha256(payload_bytes).hexdigest()
    digest_int = int(digest, 16)
    seed = digest_int + base_seed
    seed = seed % 2147483648
    return seed


def build_check_seed(base_seed: int, task_id: str) -> int:
    """Builds a deterministic Hypothesis seed shared by all agents for one task."""
    payload = f"{base_seed}:{task_id}:checks"
    payload_bytes = payload.encode("utf-8")
    digest = hashlib.sha256(payload_bytes).hexdigest()
    digest_int = int(digest, 16)
    seed = digest_int + base_seed
    seed = seed % 2147483648
    return seed

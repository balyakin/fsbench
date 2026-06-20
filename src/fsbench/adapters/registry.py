"""Adapter registry."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fsbench.adapters.aider import AiderAdapter
from fsbench.adapters.base import AgentAdapter
from fsbench.adapters.claude import ClaudeAdapter
from fsbench.adapters.codex import CodexAdapter
from fsbench.adapters.oracle import OracleAdapter
from fsbench.adapters.opencode import OpencodeAdapter
from fsbench.adapters.pi import PiAdapter
from fsbench.errors import ConfigurationError


def available_adapter_names() -> List[str]:
    """Returns all adapter names supported by the MVP."""
    return ["oracle", "codex", "aider", "claude", "opencode", "pi"]


def resolve_adapter_target(name: str, agent_aliases: Optional[Dict[str, str]] = None) -> Tuple[str, Optional[str]]:
    """Resolves a requested agent name to base adapter name and optional model."""
    target = name
    if agent_aliases is not None:
        target = agent_aliases.get(name, name)
    if ":" not in target:
        return target, None
    parts = target.split(":", 1)
    adapter_name = parts[0]
    model = parts[1]
    if not adapter_name or not model:
        raise ConfigurationError(f"invalid agent mapping for {name}: {target}")
    return adapter_name, model


def get_real_adapter(name: str, agent_aliases: Optional[Dict[str, str]] = None) -> AgentAdapter:
    """Returns a real adapter by name."""
    target = resolve_adapter_target(name, agent_aliases)
    adapter_name = target[0]
    model = target[1]
    if adapter_name == "codex":
        return CodexAdapter(name=name, model=model)
    if adapter_name == "opencode":
        return OpencodeAdapter(name=name, model=model)
    if adapter_name == "pi":
        return PiAdapter(name=name, model=model)
    if model is not None:
        raise ConfigurationError(f"adapter does not support model override: {adapter_name}")
    adapters: Dict[str, AgentAdapter] = {
        "aider": AiderAdapter(),
        "claude": ClaudeAdapter(),
    }
    if adapter_name not in adapters:
        raise ConfigurationError(f"unknown adapter: {adapter_name}")
    adapter = adapters[adapter_name]
    adapter.name = name
    return adapter


def get_adapter_for_task(
    name: str,
    solution_dir: Path,
    agent_aliases: Optional[Dict[str, str]] = None,
) -> AgentAdapter:
    """Returns an adapter for a task, including oracle."""
    target = resolve_adapter_target(name, agent_aliases)
    adapter_name = target[0]
    model = target[1]
    if adapter_name == "oracle":
        if model is not None:
            raise ConfigurationError("oracle adapter does not support model override")
        adapter = OracleAdapter(solution_dir=solution_dir)
        adapter.name = name
        return adapter
    return get_real_adapter(name, agent_aliases)

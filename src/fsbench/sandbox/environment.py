"""Environment construction for agents and checks."""

import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional

from fsbench.logging import SecretScrubber
from fsbench.models import AgentEnvMode, FsbenchSettings, ProviderProfile

SECRET_ENV_NAME_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")


def resolved_utf8_locale() -> str:
    """Returns the preferred UTF-8 locale name for deterministic subprocesses."""
    if sys.platform == "darwin":
        return "en_US.UTF-8"
    return "C.UTF-8"


def safe_path() -> str:
    """Builds a small deterministic PATH containing Python and common system bin dirs."""
    executable_path = Path(sys.executable)
    parts = [
        str(executable_path.parent),
        str(executable_path.resolve().parent),
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    unique_parts: Dict[str, str] = {}
    for part in parts:
        if Path(part).exists():
            unique_parts[part] = part
    return os.pathsep.join(unique_parts)


def deterministic_env(workspace_root: Path) -> Dict[str, str]:
    """Builds deterministic environment variables common to agents and checks."""
    locale_name = resolved_utf8_locale()
    home = workspace_root / ".fsbench_home"
    return {
        "PATH": safe_path(),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "LC_ALL": locale_name,
        "LANG": locale_name,
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "HYPOTHESIS_STORAGE_DIRECTORY": str(workspace_root / ".hypothesis"),
    }


def build_agent_env(
    workspace_root: Path,
    settings: FsbenchSettings,
    provider_profile: Optional[ProviderProfile],
    scrubber: SecretScrubber,
) -> Dict[str, str]:
    """Builds a sanitized environment for an agent subprocess."""
    if settings.agent_env == AgentEnvMode.HOST:
        env = dict(os.environ)
        _register_host_env_secrets(env, scrubber)
        return env

    env = deterministic_env(workspace_root)
    if provider_profile is None:
        return env

    allowed_names = set(provider_profile.env_allowlist)
    if provider_profile.base_url_env is not None:
        allowed_names.add(provider_profile.base_url_env)
    for env_name in sorted(allowed_names):
        value = os.environ.get(env_name)
        if value is None:
            continue
        scrubber.register_secret(env_name=env_name, value=value)
        if settings.egress.strict and env_name != provider_profile.base_url_env:
            continue
        env[env_name] = value
    return env


def _register_host_env_secrets(env: Dict[str, str], scrubber: SecretScrubber) -> None:
    for env_name, value in env.items():
        upper_name = env_name.upper()
        has_secret_name = any(part in upper_name for part in SECRET_ENV_NAME_PARTS)
        if has_secret_name:
            scrubber.register_secret(env_name=env_name, value=value)


def build_check_env(workspace_root: Path, hypothesis_seed: int) -> Dict[str, str]:
    """Builds a deterministic environment for check subprocesses."""
    env = deterministic_env(workspace_root)
    env["HYPOTHESIS_SEED"] = str(hypothesis_seed)
    return env


def binary_path(name: str) -> Optional[str]:
    """Returns an executable path using fsbench's safe PATH only."""
    return shutil.which(name, path=safe_path())

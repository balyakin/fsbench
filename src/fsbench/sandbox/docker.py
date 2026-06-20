"""Docker sandbox placeholder for post-MVP work."""

from pathlib import Path


class DockerBackend:
    """Placeholder Docker backend required by the MVP spec."""

    async def enter(self, root: Path) -> None:
        """Raises a clear error because Docker sandboxing is not implemented in MVP."""
        raise NotImplementedError("DockerBackend is intentionally not implemented in fsbench MVP; use process or bwrap")

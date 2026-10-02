"""Repository paths used by checkout-based ear-tag tooling."""

from pathlib import Path


def find_repository_root(start: Path | None = None) -> Path:
    """Find the checkout containing the Python project and ear-tag spec."""
    origin = Path(start or __file__).resolve()
    if origin.is_file():
        origin = origin.parent
    for candidate in (origin, *origin.parents):
        if ((candidate / "pyproject.toml").is_file()
                and (candidate / "hardware" / "spec.yaml").is_file()):
            return candidate
    # Keep package imports usable from an installed wheel. Checkout-only commands
    # will then resolve defaults from the caller's working directory.
    return Path.cwd().resolve()


ROOT = find_repository_root()
DEFAULT_SPEC = ROOT / "hardware" / "spec.yaml"
DEFAULT_OUTPUT = ROOT / "results" / "mvp2"
SCENARIOS = ("NORMAL", "ACTIVE", "ALERT", "WORST_REASONABLE_CASE")


def resolve_user_path(path: Path) -> Path:
    """Resolve a user-supplied path before passing it to subprocesses.

    The twin invokes several tools with ``cwd=ROOT``. Leaving relative CLI
    paths unresolved would make the parent process read them relative to its
    current directory while child processes read them relative to the checkout.
    """
    return path.expanduser().resolve()

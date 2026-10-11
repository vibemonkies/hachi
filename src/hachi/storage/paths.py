"""Owner-isolated workspace layout and approved roots.

Files are selected by opaque names that this module validates, never by a path a browser
supplied. Every lookup stays directly under its approved root and refuses symlinks.
"""

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

# Letters, digits, '.', '_' and '-'; no separators and no leading dot, so never '.' or '..'.
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

DEFAULT_WORKSPACES = Path("~/hachi/workspaces")
DEFAULT_ARTIFACTS = Path("~/hachi/artifacts")


class PathRefused(ValueError):
    """A name or location outside the approved layout."""


def is_name(value: str) -> bool:
    return bool(_NAME.fullmatch(value))


def child(root: Path, name: str) -> Path:
    """`root/name` for an opaque name. The entry may not exist yet; if it does, no symlink."""
    if not is_name(name):
        raise PathRefused("not an approved name")
    candidate = root / name
    try:
        info = candidate.lstat()
    except FileNotFoundError:
        return candidate
    if stat.S_ISLNK(info.st_mode):
        raise PathRefused("symlinks are refused under approved roots")
    if candidate.resolve().parent != root.resolve():
        raise PathRefused("entry escapes its approved root")
    return candidate


def private_directory(path: Path) -> Path:
    """Create (mode 0700) or accept an existing private directory that is not a symlink."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise PathRefused(f"{path.name} must be a real directory")
    if info.st_mode & 0o077:
        raise PathRefused(f"{path.name} must be private (mode 0700)")
    return path


def remove_tree(path: Path) -> None:
    """Delete a private directory tree without following symlinks."""
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or not path.is_dir():
        path.unlink()
        return
    for entry in os.scandir(path):
        target = Path(entry.path)
        if entry.is_dir(follow_symlinks=False):
            remove_tree(target)
        else:
            target.unlink()
    path.rmdir()


@dataclass(frozen=True)
class Workspace:
    """`<workspaces>/<owner>/` from docs/DEVELOPMENT.md; mutable API state lives in `state/`."""

    owner: str
    root: Path

    @classmethod
    def for_owner(cls, owner: str, workspaces: Path | None = None) -> "Workspace":
        base = (workspaces or DEFAULT_WORKSPACES).expanduser()
        return cls(owner, child(base, owner))

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def default_database(self) -> Path:
        return self.state / "metadata.sqlite3"

    @property
    def imports(self) -> Path:
        return self.state / "imports"

    @property
    def uploads(self) -> Path:
        return self.state / "uploads"

    def import_directory(self, import_id: str) -> Path:
        return child(self.imports, import_id)

"""Owner-isolated workspace layout and approved roots.

Files are selected by opaque names that this module validates, never by a path a browser
supplied. Every lookup stays directly under its approved root and refuses symlinks.
"""

import os
import re
import stat
import subprocess
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
    """Create or accept a real directory private to the current OS user."""
    created = False
    try:
        path.mkdir(mode=0o700, parents=True)
        created = True
    except FileExistsError:
        pass
    info = path.lstat()
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or (getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    ):
        raise PathRefused(f"{path.name} must be a real directory")
    if os.name == "nt":
        _private_windows_directory(path, created)
    elif info.st_mode & 0o077:
        raise PathRefused(f"{path.name} must be private (mode 0700)")
    return path


def _private_windows_directory(path: Path, created: bool) -> None:
    """Set new directory ACLs and validate existing ACLs without widening access."""
    script = r"""
$ErrorActionPreference = 'Stop'
try {
    $path = $env:HACHI_PRIVATE_DIRECTORY
    $item = Get-Item -LiteralPath $path -Force
    if (!$item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Directory is not a real directory'
    }
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $allowed = @($sid.Value, 'S-1-5-18', 'S-1-5-32-544')
    if ($env:HACHI_PRIVATE_DIRECTORY_CREATED -eq '1') {
        $acl = New-Object Security.AccessControl.DirectorySecurity
        $acl.SetAccessRuleProtection($true, $false)
        $acl.SetOwner($sid)
        foreach ($value in $allowed) {
            $principal = New-Object Security.Principal.SecurityIdentifier($value)
            $rule = New-Object Security.AccessControl.FileSystemAccessRule(
                $principal, 'FullControl', 'ContainerInherit, ObjectInherit', 'None', 'Allow')
            $acl.AddAccessRule($rule)
        }
        [IO.Directory]::SetAccessControl($path, $acl)
    }
    $acl = [IO.Directory]::GetAccessControl($path)
    if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value) {
        throw 'Directory owner is not the current user'
    }
    if (!$acl.AreAccessRulesProtected) {
        throw 'Directory permissions must not inherit access'
    }
    $ownerAllowed = $false
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq 'Allow' -and
            $rule.IdentityReference.Value -notin ($allowed + @('S-1-3-4'))) {
            throw 'Directory permits access by another principal'
        }
        if ($rule.AccessControlType -eq 'Allow' -and
            $rule.IdentityReference.Value -in @($sid.Value, 'S-1-3-4')) {
            $ownerAllowed = $true
        }
    }
    if (!$ownerAllowed) { throw 'Directory must explicitly permit its owner access' }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""
    environment = os.environ.copy()
    environment["HACHI_PRIVATE_DIRECTORY"] = str(path.absolute())
    environment["HACHI_PRIVATE_DIRECTORY_CREATED"] = "1" if created else "0"
    powershell = Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
            env=environment,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PathRefused(f"{path.name} privacy could not be verified") from error
    if result.returncode:
        raise PathRefused(f"{path.name} must be private to the current Windows user")


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

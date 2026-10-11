"""Approved roots resolve opaque names only; metadata migrates once and keeps contract JSON."""

import pytest

from hachi.api.settings import Settings, SettingsError, parse_pin
from hachi.storage import Metadata, PathRefused, Workspace, child, private_directory


def test_child_refuses_traversal_and_symlinks(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    for name in ("..", ".", "a/b", "../etc", ".hidden", "", "x" * 200, "a\x00b"):
        with pytest.raises(PathRefused):
            child(root, name)
    (root / "link").symlink_to(tmp_path)
    with pytest.raises(PathRefused):
        child(root, "link")
    assert child(root, "snapshot-1.2_ok") == root / "snapshot-1.2_ok"


def test_private_directories(tmp_path):
    path = private_directory(tmp_path / "state")
    assert path.stat().st_mode & 0o777 == 0o700
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    with pytest.raises(PathRefused):
        private_directory(shared)


def test_metadata_migrates_once(tmp_path):
    path = tmp_path / "metadata.sqlite3"
    Metadata(path).close()
    again = Metadata(path)
    assert again.check() and not again.subject_known("anyone")
    again.close()


def test_settings_from_environment(tmp_path):
    env = {
        "HACHI_OWNER": "justin06lee",
        "HACHI_WORKSPACES": str(tmp_path),
        "HACHI_GIT_SHA": "c" * 40,
        "HACHI_SERVE_ARTIFACTS": f"model-a@{'d' * 64}",
    }
    settings = Settings.from_environment(environ=env)
    assert settings.port == 8716
    assert settings.workspace == Workspace("justin06lee", tmp_path / "justin06lee")
    assert settings.database == tmp_path / "justin06lee" / "state" / "metadata.sqlite3"
    assert settings.served_artifacts[0].artifact_id == "model-a"
    assert Settings.from_environment(environ=env | {"HACHI_DB_PATH": "/x/db"}).database.name == "db"
    for broken in (
        {"HACHI_OWNER": "../x"},
        {"HACHI_SERVE_ARTIFACTS": "model-a"},
        {"HACHI_DATASET_SNAPSHOTS": "snap"},
    ):
        with pytest.raises(SettingsError):
            Settings.from_environment(environ=env | broken)
    with pytest.raises(SettingsError):
        parse_pin("../x@" + "d" * 64)

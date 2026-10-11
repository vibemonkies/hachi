"""Test-only stdin transport to the actual API; no socket or private data source."""

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from hachi.api.app import create_app
from hachi.api.settings import Settings
from hachi.storage import Workspace

with TemporaryDirectory(prefix="hachi-checkins-cutoff-") as directory:
    root = Path(directory)
    workspace = Workspace.for_owner("ezzy1630", root / "workspaces")
    settings = Settings(
        owner="ezzy1630",
        workspace=workspace,
        database=workspace.default_database,
        artifact_root=root / "artifacts",
        git_sha="synthetic-cutoff-test",
    )
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        print(json.dumps({"ready": True}), flush=True)
        for line in sys.stdin:
            request = json.loads(line)
            response = client.request(
                request["method"],
                request["url"],
                headers=request.get("headers"),
                content=request.get("body"),
            )
            print(json.dumps({"status": response.status_code, "body": response.text}), flush=True)

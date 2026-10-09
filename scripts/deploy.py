"""Stage and publish the standard-library-only Fabric notebook."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]


def git_commit():
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "uncommitted"


def publish(directory, workspace_id, stage):
    from azure.identity import AzureCliCredential
    from fabric_cicd import FabricWorkspace, publish_all_items

    workspace = FabricWorkspace(
        workspace_id=workspace_id,
        repository_directory=str(directory),
        environment=stage,
        item_type_in_scope=["Notebook"],
        token_credential=AzureCliCredential(),
    )
    publish_all_items(workspace)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", default=os.getenv("FABRIC_WORKSPACE_ID"))
    parser.add_argument("--stage", choices=["dev", "test", "prod"], required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--manifest", type=Path, default=ROOT / "deployment-manifest.json")
    args = parser.parse_args(argv)
    if not args.workspace_id:
        parser.error("--workspace-id or FABRIC_WORKSPACE_ID is required")
    workspace_id = str(UUID(args.workspace_id))
    if UUID(workspace_id).int == 0:
        raise ValueError("Target workspace must be a nonzero GUID")
    staging = ROOT / ".staging"
    staging.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="deploy-", dir=staging) as temporary:
        directory = Path(temporary) / "workspace"
        shutil.copytree(ROOT / "workspace", directory)
        manifest = {
            "commit": git_commit(), "stage": args.stage, "workspace_id": workspace_id,
            "scope": ["Notebook"], "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "status": "dry-run" if args.dry_run else "started",
        }
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if not args.dry_run:
            completed = False
            try:
                publish(directory, workspace_id, args.stage)
                completed = True
            finally:
                manifest["status"] = "published" if completed else "failed"
                args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

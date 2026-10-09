import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import deploy

TARGET = "11111111-1111-4111-8111-111111111111"


class WorkloadTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / ".staging"
        scratch.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_platform_and_notebook_metadata(self):
        path = ROOT / "workspace/PrintCurrentDateInline.Notebook"
        platform = json.loads((path / ".platform").read_text())
        self.assertEqual(platform["metadata"]["type"], "Notebook")
        self.assertEqual(platform["metadata"]["displayName"], path.name.removesuffix(".Notebook"))
        self.assertTrue(platform["$schema"].endswith("/2.0.0/schema.json"))
        self.assertEqual(platform["config"]["version"], "2.0")
        UUID(platform["config"]["logicalId"])
        source = (path / "notebook-content.py").read_text()
        compile(source, "notebook", "exec")
        metadata = [json.loads("\n".join(
            line.removeprefix("# META ") for line in chunk.splitlines() if line.startswith("# META ")
        )) for chunk in source.split("# METADATA ********************")[1:]]
        self.assertEqual(metadata[0]["dependencies"], {})
        self.assertEqual(metadata[0]["kernel_info"]["name"], "synapse_pyspark")
        self.assertEqual(metadata[1]["language"], "python")
        self.assertEqual(len(list((ROOT / "workspace").glob("*.Environment"))), 0)

    def test_inline_prints_deterministic_utc_date(self):
        module = ModuleType("datetime")
        module.datetime = Mock()
        module.datetime.now.return_value = datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)
        module.timezone = timezone
        output = io.StringIO()
        source = (ROOT / "workspace/PrintCurrentDateInline.Notebook/notebook-content.py").read_text()
        with patch.dict(sys.modules, {"datetime": module}), contextlib.redirect_stdout(output):
            exec(compile(source, "notebook", "exec"), {})
        self.assertEqual(output.getvalue(), "2026-10-09\n")
        module.datetime.now.assert_called_once_with(timezone.utc)

    def arguments(self):
        return ["--workspace-id", TARGET, "--stage", "dev",
                "--manifest", str(self.directory / "manifest.json")]

    def test_dry_run_never_imports_sdk_or_changes_sources(self):
        before = {str(p): p.read_bytes() for p in (ROOT / "workspace").rglob("*") if p.is_file()}
        with patch.dict(sys.modules, {"fabric_cicd": None, "azure.identity": None}), contextlib.redirect_stdout(io.StringIO()):
            deploy.main(self.arguments() + ["--dry-run"])
        self.assertEqual(json.loads((self.directory / "manifest.json").read_text())["status"], "dry-run")
        self.assertEqual(before, {str(p): p.read_bytes() for p in (ROOT / "workspace").rglob("*") if p.is_file()})

    def test_live_stages_then_publishes(self):
        def inspect(directory, workspace, stage):
            self.assertEqual((workspace, stage), (TARGET, "dev"))
            self.assertTrue((directory / "PrintCurrentDateInline.Notebook/.platform").exists())
            self.assertNotEqual(directory, ROOT / "workspace")
        with patch.object(deploy, "publish", side_effect=inspect), contextlib.redirect_stdout(io.StringIO()):
            deploy.main(self.arguments())
        self.assertEqual(json.loads((self.directory / "manifest.json").read_text())["status"], "published")

    def test_publish_uses_azure_cli_and_notebook_only(self):
        sdk = ModuleType("fabric_cicd")
        sdk.FabricWorkspace = Mock()
        sdk.publish_all_items = Mock()
        identity = ModuleType("azure.identity")
        identity.AzureCliCredential = Mock()
        with patch.dict(sys.modules, {"fabric_cicd": sdk, "azure.identity": identity}):
            deploy.publish(self.directory, TARGET, "prod")
        self.assertEqual(sdk.FabricWorkspace.call_args.kwargs["item_type_in_scope"], ["Notebook"])
        self.assertIs(sdk.FabricWorkspace.call_args.kwargs["token_credential"], identity.AzureCliCredential.return_value)
        sdk.publish_all_items.assert_called_once_with(sdk.FabricWorkspace.return_value)

    def test_live_failure_records_failure(self):
        with patch.object(deploy, "publish", side_effect=RuntimeError("publish failed")):
            with self.assertRaises(RuntimeError):
                deploy.main(self.arguments())
        self.assertEqual(json.loads((self.directory / "manifest.json").read_text())["status"], "failed")

    def test_invalid_workspace_rejected_before_publish(self):
        with patch.object(deploy, "publish") as publish:
            with self.assertRaises(ValueError):
                deploy.main(["--workspace-id", "not-a-guid", "--stage", "dev"])
        publish.assert_not_called()

    def test_workflows_are_parseable_and_use_oidc(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            self.assertIn("jobs", yaml.safe_load(path.read_text()))
        workflow = yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text())
        self.assertEqual(workflow["permissions"]["id-token"], "write")
        self.assertFalse(workflow["concurrency"]["cancel-in-progress"])
        self.assertEqual(workflow["jobs"]["deploy"]["environment"], "${{ inputs.stage }}")


if __name__ == "__main__":
    unittest.main()

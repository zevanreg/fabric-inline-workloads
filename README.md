# Fabric inline workloads

Standalone comparison workload repository in the five-repository demo:

| Repository | Responsibility |
| --- | --- |
| `fabric-date-library` | Versioned UTC date wheel release |
| `fabric-wheel-infrastructure` | Separate wheel dev/test/prod workspaces |
| `fabric-wheel-workloads` | Environment/wheel plus importing Notebook |
| `fabric-inline-infrastructure` | Inline dev/test/prod workspaces on existing capacity |
| **`fabric-inline-workloads`** | Standard-library-only Notebook deployment |

`PrintCurrentDateInline` executes:

```python
from datetime import datetime, timezone
print(datetime.now(timezone.utc).isoformat(timespec="seconds"))
```

It prints the current UTC date and time as an ISO 8601 timestamp, with no wheel, custom Environment,
Lakehouse, notebook `%pip`, or external runtime package. Fabric still uses
a Spark/Python notebook and needs an active supported capacity; Python 3.11
is the **CI/deployment tooling** version, not a custom Fabric runtime.

## First-time setup

1. Run `fabric-inline-infrastructure` with your existing Fabric capacity.
   Take the dev/test/prod workspace IDs from `workspace-ids.json`. This repo
   does not create capacity, workspaces, or change capacity assignment.
2. Publish this local repo yourself. It starts on `main` without commits,
   remotes or a GitHub repository. Protect `main` and require **Offline CI**.
3. Create GitHub environments **dev**, **test**, **prod**, each with:

   | Variable | Value |
   | --- | --- |
   | `AZURE_CLIENT_ID` | Deployment Entra application/client ID |
   | `AZURE_TENANT_ID` | Entra tenant ID |
   | `FABRIC_WORKSPACE_ID` | Corresponding inline workspace ID |

4. Configure Entra OIDC federated credentials:
   issuer `https://token.actions.githubusercontent.com`,
   audience `api://AzureADTokenExchange`,
   subject `repo:OWNER/fabric-inline-workloads:environment:dev`;
   repeat for `test` and `prod`. Workflow `azure/login@v2` obtains an Azure
   CLI session and Python uses `AzureCliCredential`. No Azure client secret
   or subscription ID is required for this Fabric-only workflow.
5. Enable the Fabric tenant setting permitting service principals to use
   Fabric APIs for the principal's security group; grant workspace access
   supporting Notebook writes (typically Contributor/Member). Reusing the
   infrastructure principal/workspace owner is simplest. Azure capacity RBAC
   does not itself grant Fabric workspace access.
6. Require reviewer approval on **test/prod**, restrict deployment branches,
   and permit only trusted reviewed workload SHAs. No library token is needed.

## Offline verification (PowerShell)

```powershell
Set-Location C:\repos\fabric-inline-workloads
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\deploy.py --stage dev --workspace-id 11111111-1111-4111-8111-111111111111 --dry-run
```

The example GUID is only for offline staging. Dry-run requires just Python's
standard library and never imports/constructs `FabricWorkspace`, obtains
credentials, or calls APIs. Tests also need PyYAML. Both run without Fabric
access. Sources are copied under the repo's ignored `.staging` directory,
which is cleaned on exit, and an ignored `deployment-manifest.json` captures
stage/workspace/commit/time/status. Tracked sources are never modified.

`fabric-cicd==1.3.0`, `azure-identity==1.25.1`, and `PyYAML==6.0.3` are pinned.
SDK 1.3.0 exists on public PyPI and requires Python >=3.9,<3.14. Use Python 3.11
and an approved index exposing that version; Python 3.14/package proxy
filtering can make it appear unavailable. Do not silently upgrade the SDK.

For live local deployment, run `az login --tenant YOUR_TENANT_ID`, use your
real workspace ID, and omit `--dry-run`. `FABRIC_WORKSPACE_ID` is a supported
fallback for `--workspace-id`. Before the first commit local evidence records
`uncommitted`; GitHub deployment requires a full commit SHA.

## Deploy and promote

1. Commit a notebook change, pass CI, then run **Deploy inline workloads**
   (`workflow_dispatch`) from trusted `main`, choosing stage **dev** and
   the full 40-character workload commit SHA.
2. The workflow checks out and verifies that exact SHA, runs offline tests,
   previews deployment without network calls, logs in with OIDC, and calls
   `publish_all_items` scoped to `Notebook`. No orphan cleanup is performed.
3. In the target Fabric workspace, open `PrintCurrentDateInline`, verify it
   has no custom Environment/Lakehouse dependency, and run it. Confirm the
   single date line equals the **UTC** date at execution time, not necessarily
   your local date. This manual live smoke test requires active capacity.
   The workflow publishes definitions; it does **not** execute notebooks.
4. Dispatch the **same SHA** to **test**, approve and smoke-test, then dispatch
   the same SHA to **prod** with approval and the final smoke test. Retain
   deployment evidence artifacts with commit, workspace, stage and status.

Rollback: dispatch a previously approved SHA to the same target stage.
The publisher updates matching notebook definitions; cloud partial updates
are not automatically rolled back if a deployment fails.

## Inline versus wheel release flow

All date logic lives in this notebook, so logic changes require a notebook
commit and a Notebook deployment. There is no library release/pin step.
In `fabric-wheel-workloads`, the notebook calls the shared library; changing
only the library instead releases a new wheel, updates the committed release
pin there, and dispatches Environment-only promotion without notebook edits.

## Operational boundaries

- No actual cloud deployment, remote creation or Fabric execution was done
  during local repository creation. Offline tests validate metadata, the
  deterministic UTC result, mocked SDK calls, staging, and failure evidence;
  they do not establish live API/capacity compatibility.
- Workload and infrastructure repositories must target their matching
  workspaces. Do not point both demos or multiple stages at one shared dev
  workspace. Do not also enable Fabric Git synchronization on these items.
- Per-stage concurrency prevents cancelling an active publish but GitHub
  may replace older pending runs. Verify the completed SHA before promotion.
  This lock does not coordinate other repositories.
- Authorization failures: check the federated environment subject, tenant
  service-principal setting, workspace role, active capacity and variables.
- This is deliberately only a date-printing demo, not a data ingestion,
  scheduling, or end-to-end production monitoring example.

References: [fabric-cicd](https://microsoft.github.io/fabric-cicd/latest/),
[Azure Login OIDC](https://github.com/Azure/login#login-with-openid-connect-oidc-recommended).

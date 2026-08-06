# EdgeRunner Automation Tasks

This repo runs standalone Python automation scripts from GitHub Actions. Each
task is a complete script under `tasks/`: it can call APIs, transform data, use
`dlt`, write Google Sheets, trigger another service, or do any other custom
automation.

The main execution path is GitHub Actions. Local setup is only needed when you
want to edit or regenerate workflows from your machine.

## Project Shape

- `tasks/demo/_template.py`: starting point to copy when adding a task.
- `tasks/demo/jsonplaceholder_posts.py`: complete example task for a public posts API.
- `tasks/demo/github_cpython_repo.py`: complete example task for GitHub's public API.
- `tasks/shared/google_sheet_to_sheet.py`: reusable task that is not tied to one client.
- `config/tasks.toml`: task metadata such as script path, cron, sheet id, and tab.
- `src/edgerunner/sheets.py`: small shared helper for writing records to Sheets.
- `src/edgerunner/secrets.py`: small shared helper for Secret Manager.
- `scripts/generate_workflows.py`: regenerates `.github/workflows/*.yml`.

## Local Setup

Install Python 3.11+ first.

Windows options:

```powershell
# Option 1: winget
winget install Python.Python.3.11

# Option 2: download the installer from https://www.python.org/downloads/windows/
# During install, check "Add python.exe to PATH".
```

Verify Windows can find Python:

```powershell
py -3.11 --version
```

macOS options:

```bash
# Option 1: Homebrew
brew install python@3.11

# Option 2: download the installer from https://www.python.org/downloads/macos/
```

Verify macOS can find Python:

```bash
python3.11 --version
```

Create and install the virtual environment on Windows:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -c "import pandas as pd; print(pd.__version__)"
```

Create and install the virtual environment on macOS:

```bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install -U pip
./.venv/bin/python -m pip install -e .
./.venv/bin/python -c "import pandas as pd; print(pd.__version__)"
```

Run one task locally only if you want a quick manual check:

```powershell
.\.venv\Scripts\python.exe tasks\demo\github_cpython_repo.py --task-name github_cpython_repo --skip-sheet
.\.venv\Scripts\python.exe tasks\demo\github_cpython_repo.py --github_cpython_repo --skip-sheet
```

macOS equivalent:

```bash
./.venv/bin/python tasks/demo/github_cpython_repo.py --task-name github_cpython_repo --skip-sheet
./.venv/bin/python tasks/demo/github_cpython_repo.py --github_cpython_repo --skip-sheet
```

Run the automated unit tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

macOS equivalent:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

The `.github/workflows/unit_tests.yml` workflow runs the same test command on
every push and pull request. To make failed tests block merges, enable a branch
protection rule in GitHub and require the `unit-tests` status check before
merging.

## Adding A Task

A task is one automation job. It has two parts:

- A Python script under `tasks/` that contains the actual logic.
- One `[[tasks]]` entry in `config/tasks.toml` that tells the framework which
  script to run, what default settings to pass in, and whether GitHub Actions
  should schedule it.

The Python script should focus on business logic: call an API, transform data,
write a Google Sheet, call another task, or anything else you need. The TOML
entry should hold configuration values that may change by environment, client,
schedule, Sheet ID, API URL, date range, or manual override.

### 1. Choose Where The Script Should Live

Put reusable scripts in `tasks/shared`. Put client-specific scripts in their own
folder, such as `tasks/bestbuy`, `tasks/petco`, or `tasks/my_client`.

Example: create a new client folder and copy the starter template:

```powershell
New-Item -ItemType Directory -Force tasks\my_client
Copy-Item tasks\demo\_template.py tasks\my_client\my_job.py
```

Why this matters: the folder name becomes part of the generated workflow name.
For example, `tasks/my_client/my_job.py` generates a workflow named
`my_client / my_job`.

### 2. Write The Task Script

Every task script should expose a `run(settings)` function. The framework passes
one `TaskSettings` object into that function.

Minimal example:

```python
from __future__ import annotations

from typing import Any

from edgerunner.task_config import TaskSettings, run_task


def run(settings: TaskSettings) -> dict[str, Any]:
    # Read values from config/tasks.toml.
    endpoint = settings["api_endpoint"]
    timeout = settings.get("api_timeout_seconds", 30)

    # Put your real automation logic here:
    # - call an API
    # - transform records
    # - write to a Google Sheet
    # - call another task's run(settings)
    print(f"Would call {endpoint} with timeout={timeout}")

    return {
        "task": settings.name,
        "endpoint": endpoint,
        "timeout": timeout,
    }


def main() -> None:
    run_task(run)


if __name__ == "__main__":
    main()
```

Why this shape matters:

- `run(settings)` is the reusable business function. Other task scripts can
  import it and call it directly.
- `run_task(run)` is only the command-line wrapper. It loads TOML, applies manual
  overrides, builds `TaskSettings`, and then calls `run(settings)`.

### 3. Add The TOML Config

Add one `[[tasks]]` entry to `config/tasks.toml`. The `name` must be unique.
The `script_path` must point to the Python file you created.

```toml
[[tasks]]
name = "my_job"
script_path = "tasks/my_client/my_job.py"
gcp_auth = true
api_endpoint = "https://api.example.com/data"
api_timeout_seconds = 30
```

Required fields:

- `name`: the task ID. This is how the workflow tells the script which TOML
  entry to load.
- `script_path`: the Python script to run.

Optional framework fields:

- `cron_setting`: GitHub Actions cron in UTC. Add this only when the task should
  run automatically.
- `gcp_auth`: whether the generated workflow should authenticate to GCP.
  Defaults to `true` when omitted.
- `sheet_id`: the default Google Sheet ID. Add this when your script reads from
  or writes to a Google Sheet.
- `tab_name`: the default Sheet tab name. Add this when your script reads from
  or writes to a Google Sheet.
- `start_date_offset` and `end_date_offset`: optional date-window defaults.
  Use these when the task needs a date range, such as today minus 30 days through
  yesterday. Ignore them when the task does not need dates.
- `manual_overrides`: optional manual-run inputs for GitHub Actions
  `workflow_dispatch`. Use this when someone should be able to override selected
  TOML values before manually running the workflow.

Custom script fields:

You can add any extra fields your script needs. The framework preserves them and
passes them into `settings`.

Examples:

```toml
api_endpoint = "https://api.example.com/data"
api_timeout_seconds = 30
api_query = { limit = 100, status = "active" }
```

For a Sheet-writing task, add Sheet config:

```toml
sheet_id = "YOUR_GOOGLE_SHEET_ID"
tab_name = "my_job"
sheet_write_mode = "upsert"
sheet_upsert_key_columns = ["date", "store_id"]
```

These custom fields do not have special meaning to the framework unless a shared
helper reads them. Your Python script decides what they mean.

Every key in the TOML entry is available in Python:

```python
endpoint = settings["api_endpoint"]
timeout = settings.get("api_timeout_seconds", 30)
```

For a non-Sheet task, you can omit `sheet_id` and `tab_name`; the convenience
properties return empty strings.

For a Sheet task, read them with the convenience properties:

```python
sheet_id = settings.sheet_id
tab_name = settings.tab_name
```

Known fields such as `name`, `script_path`, `cron_setting`, `sheet_id`,
`tab_name`, and `gcp_auth` have convenience properties. Custom fields are
preserved in `settings.params` and can be accessed with `settings["key"]`.

### 4. Decide Whether It Should Run Automatically

If the task should only run manually from GitHub Actions, do not add
`cron_setting`.

If the task should run on a schedule, add `cron_setting`:

```toml
cron_setting = "0 13,21 * * *"
```

GitHub Actions cron is always UTC. The example above runs at 13:00 UTC and
21:00 UTC every day. During New York daylight time, that is 9:00 AM and 5:00 PM
New York time.

Why this matters: manual-only demo tasks should not have cron. Production
automations that must run every day should have cron.

### 5. Regenerate The GitHub Workflow

After editing `config/tasks.toml`, regenerate workflow files:

```powershell
.\.venv\Scripts\python.exe scripts\generate_workflows.py
```

This creates or updates a file under `.github/workflows`. GitHub Actions only
loads workflow files from that directory's first level. The generator prefixes
workflow filenames with the folder under `tasks`, so:

```text
tasks/my_client/my_job.py
```

generates something like:

```text
.github/workflows/my_client__my_job.yml
```

The generated workflow runs this command in GitHub Actions:

```text
python tasks/my_client/my_job.py --task-name my_job
```

That is why `name` and `script_path` both matter: `script_path` selects the
file, and `--task-name` selects the TOML entry.

### 6. Enable The Local Git Hook

Do this once per local clone:

```powershell
git config core.hooksPath .githooks
```

Why this matters: when you commit a change to `config/tasks.toml`, the hook
automatically runs `scripts/generate_workflows.py` so the generated workflow
stays in sync with the TOML.

### 7. Test The Task Locally

Run the task without writing to Google Sheets:

```powershell
.\.venv\Scripts\python.exe tasks\my_client\my_job.py --task-name my_job --skip-sheet
```

You can also use the shorthand task name:

```powershell
.\.venv\Scripts\python.exe tasks\my_client\my_job.py --my_job
```

Why this matters: local runs catch basic Python errors before you push. The
`--skip-sheet` flag is available to the script as `settings.skip_sheet`, so Sheet
writing tasks can safely test read/transform logic without changing a Sheet.

### 8. Push To A Testing Branch And Run In GitHub Actions

After local testing succeeds, create a testing branch. Use this naming pattern:

```text
testing-{description}
```

Example:

```powershell
git switch -c testing-my-job
git add tasks\my_client\my_job.py config\tasks.toml .github\workflows\my_client__my_job.yml
git commit -m "Add my_job automation task"
git push -u origin testing-my-job
```

Why this matters: the first real GitHub Actions run should happen on your own
testing branch, not directly on `main`. That lets you test credentials,
workflow_dispatch inputs, Sheet permissions, API access, and logs before asking
for review.

Open the Actions tab in GitHub and select the generated workflow. Use the branch
dropdown to choose your `testing-{description}` branch.

For a manual-only task, choose the generated workflow and click **Run workflow**.
For a scheduled task, GitHub runs it from the default branch according to
`cron_setting`, but you should still manually run it once from your testing
branch before merging.

If the task uses GCP, make sure the repo has these GitHub secrets:

```text
GCP_WORKLOAD_IDENTITY_PROVIDER
GCP_SERVICE_ACCOUNT
```

If the task writes to Google Sheets, share the Sheet with the service account
email in `GCP_SERVICE_ACCOUNT`.

When the action finishes, check:

- The GitHub Actions run is green.
- The task log shows the expected inputs, date range, row counts, or API result.
- The target Google Sheet or downstream system has the expected output.
- Manual overrides work if the task exposes workflow inputs.
- Slack alerting is skipped cleanly when `SLACK_WEBHOOK_URL` is empty, or sends
  the expected alert when configured.

If something fails, update the same testing branch and rerun the workflow.

After the GitHub Actions test succeeds, open a pull request from
`testing-{description}` and ask for review. The PR should include the task
script, the TOML entry, the generated workflow, and any README/test updates that
belong with the task.

### 9. Reuse Or Combine Tasks

The same Python script can power multiple tasks. Add multiple TOML entries with
different `name` values and the same `script_path`; the workflow passes the
selected task name with `--task-name`, and the script loads that entry's
parameters.

One task can also call another task:

```python
from edgerunner.task_config import TaskSettings, run_task
from tasks.shared.google_sheet_to_sheet import run as sheet_transfer


def run(settings: TaskSettings):
    transfer_result = sheet_transfer(settings)
    print(f"Transferred {transfer_result['record_count']} rows")
    return transfer_result


if __name__ == "__main__":
    run_task(run)
```

This works because every task uses the same `run(settings)` shape.

## Manual Workflow Overrides

Tasks can expose selected TOML settings as inputs when someone manually runs a
workflow from GitHub Actions. Scheduled runs ignore these inputs and use the
default values checked into `config/tasks.toml`.

Date windows use reserved offset settings:

```toml
start_date_offset = -30
end_date_offset = -1
```

When a task has these fields, the generated manual workflow gets reserved
`startdate` and `enddate` inputs. Enter dates as `YYYY-MM-DD`; the framework
converts them back into `start_date_offset` and `end_date_offset` before the task
script reads `settings`. For example, if today is `2026-08-01`, entering
`startdate=2026-07-02` and `enddate=2026-07-31` gives offsets `-30` and `-1`.
The framework defines "today" in `America/New_York`, even on GitHub-hosted
runners.
You do not need to list `startdate` or `enddate` in `manual_overrides`.

Task scripts should turn offsets into the API's actual query parameter names:

```python
from edgerunner.task_config import date_from_offset

params = {
    **settings.get("api_query", {}),
    "start_date": date_from_offset(settings["start_date_offset"]),
    "end_date": date_from_offset(settings["end_date_offset"]),
}
```

For non-date fields, add a `manual_overrides` list to a task:

```toml
[[tasks]]
name = "api_with_dates"
script_path = "tasks/my_client/api_with_dates.py"
cron_setting = "0 12 * * *"
sheet_id = "YOUR_GOOGLE_SHEET_ID"
tab_name = "api_with_dates"
gcp_auth = true
api_endpoint = "https://api.example.com/data"
api_query = { limit = 100 }
manual_overrides = [
  { name = "limit", path = "api_query.limit", description = "API result limit for manual runs" },
]
```

`name` becomes the GitHub Actions manual input name. `path` points to the TOML
setting to override, and can use dot notation for nested tables. Empty manual
inputs are ignored, so a manually triggered workflow can override only one field
and leave the rest at their defaults.

For local testing, pass the same values with `--override`:

```powershell
.\.venv\Scripts\python.exe tasks\my_client\api_with_dates.py --api_with_dates --override startdate=2026-08-01 --override enddate=2026-08-15
```

## Google Sheets

For checked-in tasks, put the Sheet ID directly in `config/tasks.toml`:

```toml
sheet_id = "YOUR_GOOGLE_SHEET_ID"
tab_name = "my_tab"
```

The GitHub Actions service account must have Editor access to that spreadsheet.
Share the target Sheet with the service account address, which is the value of
the `GCP_SERVICE_ACCOUNT` repository secret:

```text
YOUR_SERVICE_ACCOUNT@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

Google Sheets permissions are controlled by sharing the spreadsheet, not by a
GCP IAM role.

`write_records_to_sheet()` accepts either `list[dict]` records or a pandas
DataFrame. Pandas is part of the default project dependencies, so generated
workflows install it through `python -m pip install -e .`.

Supported `sheet_write_mode` values:

```text
replace  Clear the target tab, then write all rows.
append   Append new rows, skipping the incoming header if the target already has one.
upsert   Delete target rows whose key column exists in the incoming data, then append.
```

For `upsert`, pass `sheet_upsert_key_columns` in TOML and forward it to
`write_records_to_sheet(..., upsert_key_columns=...)`. A single-column key can
be `["date"]`; a composite key can be `["date", "store_id"]`.

### Sheet To Sheet Task

`tasks/shared/google_sheet_to_sheet.py` copies rows from one Google Sheet tab to another
Google Sheet tab. It reads columns A:F, treats the first source row as the header
row, filters records whose column A date is between 5 days ago and yesterday,
then writes the filtered pandas DataFrame to the target tab.

Update this entry in `config/tasks.toml` before running it:

```toml
[[tasks]]
name = "google_sheet_to_sheet"
script_path = "tasks/shared/google_sheet_to_sheet.py"
cron_setting = "40 16 * * *"
sheet_id = "TARGET_GOOGLE_SHEET_ID"
tab_name = "target_tab"
gcp_auth = true
source_sheet_id = "SOURCE_GOOGLE_SHEET_ID"
source_tab_name = "source_tab"
source_range = "source_tab!A:F"
start_date_offset = -5
end_date_offset = -1
sheet_write_mode = "upsert"
sheet_upsert_key_columns = ["date"]
manual_overrides = [
  { name = "source_range", path = "source_range", description = "A1 range to copy, for example source_tab!A:F" },
  { name = "startdate", path = "start_date_offset", description = "Start date, YYYY-MM-DD. Converted to start_date_offset using New York time." },
  { name = "enddate", path = "end_date_offset", description = "End date, YYYY-MM-DD. Converted to end_date_offset using New York time." },
]
```

Run it locally without writing the target Sheet:

```powershell
.\.venv\Scripts\python.exe tasks\shared\google_sheet_to_sheet.py --google_sheet_to_sheet --skip-sheet
```

Run it locally and write the target Sheet:

```powershell
.\.venv\Scripts\python.exe tasks\shared\google_sheet_to_sheet.py --google_sheet_to_sheet
```

This task uses the GitHub Actions service account from the `GCP_SERVICE_ACCOUNT`
repository secret. Share the source spreadsheet and target spreadsheet with that
service account address. Give it Viewer access on the source and Editor access
on the target.

## GitHub Actions Auth

GitHub Actions uses keyless auth through Workload Identity Federation. Required
repository secrets:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`

Both are environment specific and are not recorded in this repo. They take the
following shape, and the exact values for an environment come from the WIF setup
below:

```text
GCP_WORKLOAD_IDENTITY_PROVIDER=projects/YOUR_PROJECT_NUMBER/locations/global/workloadIdentityPools/YOUR_POOL_ID/providers/YOUR_PROVIDER_ID
GCP_SERVICE_ACCOUNT=YOUR_SERVICE_ACCOUNT@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

Each generated workflow has exactly one job and can be run manually with
`workflow_dispatch`. When `cron_setting` is present, the cron runs on the
default branch in UTC.

## Slack Alerts

Generated task workflows call a Slack Workflow Builder webhook after each run
when the `SLACK_WEBHOOK_URL` GitHub repository secret is set. If the secret is
missing or empty, the alert step prints a skip message and exits successfully.

In Slack Workflow Builder, create webhook variables with these names:

```text
task_name
task_status
finished_at
reason
error_log
job_status
task_outcome
exit_code
run_url
repository
workflow_name
branch_name
trigger
```

Generated workflows call `scripts/send_slack_alert.py` as the final step. The
script posts those variables as a JSON payload, and Slack owns the message
shape, so you can build the success/failure wording in Slack using the variables
above. `error_log` contains the last 80 task log lines on failure and is empty
on success.

## WIF Setup Reference

These commands configure GitHub Actions in one repository to impersonate a
service account in one GCP project. Fill in the five values at the top for your
own environment; the rest of the script derives from them.

```powershell
$PROJECT_ID = "YOUR_PROJECT_ID"
$REPO = "YOUR_GITHUB_OWNER/YOUR_GITHUB_REPO"
$POOL_ID = "YOUR_POOL_ID"
$PROVIDER_ID = "YOUR_PROVIDER_ID"
$SA_NAME = "YOUR_SERVICE_ACCOUNT"
$SA_EMAIL = "$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

gcloud config set project $PROJECT_ID

gcloud services enable `
  iam.googleapis.com `
  iamcredentials.googleapis.com `
  sts.googleapis.com `
  sheets.googleapis.com `
  secretmanager.googleapis.com `
  --project=$PROJECT_ID

gcloud iam service-accounts create $SA_NAME `
  --project=$PROJECT_ID `
  --display-name="EdgeRunner GitHub Actions"

gcloud iam workload-identity-pools create $POOL_ID `
  --project=$PROJECT_ID `
  --location="global" `
  --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc $PROVIDER_ID `
  --project=$PROJECT_ID `
  --location="global" `
  --workload-identity-pool=$POOL_ID `
  --display-name="$PROVIDER_ID GitHub provider" `
  --issuer-uri="https://token.actions.githubusercontent.com" `
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.ref=assertion.ref" `
  --attribute-condition="assertion.repository == '$REPO'"

$POOL_NAME = gcloud iam workload-identity-pools describe $POOL_ID `
  --project=$PROJECT_ID `
  --location="global" `
  --format="value(name)"

gcloud iam service-accounts add-iam-policy-binding $SA_EMAIL `
  --project=$PROJECT_ID `
  --role="roles/iam.workloadIdentityUser" `
  --member="principalSet://iam.googleapis.com/$POOL_NAME/attribute.repository/$REPO"

$PROVIDER_NAME = gcloud iam workload-identity-pools providers describe $PROVIDER_ID `
  --project=$PROJECT_ID `
  --location="global" `
  --workload-identity-pool=$POOL_ID `
  --format="value(name)"

Write-Host "GCP_WORKLOAD_IDENTITY_PROVIDER=$PROVIDER_NAME"
Write-Host "GCP_SERVICE_ACCOUNT=$SA_EMAIL"
```

If a task reads Google Secret Manager secrets, grant the service account access:

```powershell
gcloud secrets add-iam-policy-binding YOUR_SECRET_NAME `
  --project=$PROJECT_ID `
  --role="roles/secretmanager.secretAccessor" `
  --member="serviceAccount:$SA_EMAIL"
```

## Secrets In Task Scripts

For production, use a Secret Manager version address:

```python
from edgerunner.secrets import access_secret

token = access_secret("projects/YOUR_PROJECT_ID/secrets/YOUR_SECRET/versions/latest")
```


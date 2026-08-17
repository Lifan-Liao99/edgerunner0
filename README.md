# EdgeRunner Automation Tasks

EdgeRunner exists to meet the Edge Program's automation needs inside the
program's SOC 2 requirements. An Edge builder writes an ordinary Python script
and describes how it should run in a config-driven TOML file; the framework turns
that description into a scheduled, credential-free GitHub Actions workflow.

Each task is a complete script under `tasks/`: it can call APIs, transform data,
use `dlt`, write Google Sheets, trigger another service, or do any other custom
automation. `config/tasks.toml` supplies its schedule, manual-run inputs, and
per-task settings, so adding an automation means writing one script and one TOML
block, not hand-editing YAML.

How the compliance posture is held:

- **Workload Identity Federation for identity.** GitHub Actions exchanges its
  OIDC token for a short-lived Google Cloud service account token at run time. No
  service account key is ever created, downloaded, or committed, so there is no
  long-lived credential to rotate, leak, or audit.
- **Google Secret Manager for secrets.** Task secrets live in GSM and are read at
  run time through `src/edgerunner/secrets.py`. Nothing sensitive is stored in the
  repo, in workflow files, or on a builder's laptop.
- **GitHub Actions as the only privileged execution path.** Production runs
  happen in CI, where identity and secrets are scoped and every run is logged.
  Google Sheets access is available only there; local runs use `--skip-sheet`.
- **Generated, reviewable workflows.** `scripts/generate_workflows.py` derives
  every workflow from `config/tasks.toml`, with third-party actions pinned to
  commit SHAs. Changes to what runs in production show up as a reviewable diff.

The main execution path is GitHub Actions. Local setup is only needed when you
want to develop a task, exercise its fetch and transform logic with
`--skip-sheet`, or regenerate workflows from your machine.

## Project Shape

- `tasks/demo/_template.py`: starting point to copy when adding a task.
- `tasks/demo/jsonplaceholder_posts.py`: complete example task for a public posts API.
- `tasks/demo/github_cpython_repo.py`: complete example task for GitHub's public API.
- `tasks/shared/google_sheet_to_sheet.py`: reusable task that is not tied to one client.
- `config/tasks.toml`: task metadata such as script path, cron, sheet id, and tab.
- `src/edgerunner/sheets.py`: small shared helper for writing records to Sheets.
- `src/edgerunner/secrets.py`: small shared helper for Secret Manager.
- `scripts/generate_workflows.py`: regenerates `.github/workflows/*.yml`.
- `.github/workflows/test_workflow.yml`: permanent manual slot for testing a new
  task from a branch before it merges.
- `scripts/check_test_slot_cleared.py`: fails a pull request into `main` while
  that slot is still loaded.
- `scripts/describe_task.py`: prints a task's resolved config, so a test slot run
  reports which task it is running.

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

Enable the pre-commit hook, once per clone, so the generated workflows stay in
sync with `config/tasks.toml`:

```powershell
git config core.hooksPath .githooks
```

See [Enable The Local Git Hook](#6-enable-the-local-git-hook) for what it does and
what you have to do by hand if you skip it.

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

- `cron_setting`: GitHub Actions cron in New York time. Add this only when the
  task should run automatically.
- `gcp_auth`: whether the generated workflow should authenticate to GCP.
  Defaults to `true` when omitted.
- `is_test`: load this task into the permanent test workflow so it can be
  dispatched from a testing branch. Defaults to `false`. At most one task may set
  it to `true`, and it must be back to `false` before merging: a pull request
  into `main` fails while it is on. See
  [Testing A New Task From A Branch](#testing-a-new-task-from-a-branch).
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
cron_setting = "0 9,17 * * *"
```

Generated workflows attach `timezone: "America/New_York"` to scheduled runs. The
example above runs at 9:00 AM and 5:00 PM New York time, with daylight saving
time handled by GitHub Actions.

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

Step 6 automates this command so you do not have to remember it.

### 6. Enable The Local Git Hook

The workflows under `.github/workflows/` are generated from `config/tasks.toml`.
They are committed to the repo, so they only stay correct if someone regenerates
them after every config change. The hook does that for you.

Do this once per local clone, on Windows and macOS alike:

```powershell
git config core.hooksPath .githooks
```

Verify it took effect:

```powershell
git config --get core.hooksPath
```

That should print `.githooks`. If it prints nothing, the hook is **not** enabled.

This setting lives in `.git/config`, which is not part of the repo, so cloning
the repo does not bring it along. Every person on every machine has to run it
once.

When it is enabled, committing a change to `config/tasks.toml` prints:

```text
config/tasks.toml is staged; regenerating GitHub workflows...
Wrote .github\workflows\my_client__my_job.yml
Wrote .github\workflows\test_workflow.yml (empty)
Regenerated workflows have been staged.
```

The regenerated files are staged into the same commit, so the config and the
workflows never separate. If generation fails, for example because two tasks set
`is_test = true`, the commit is aborted and the error tells you what to fix.

#### If You Do Not Enable The Hook

Then regenerating is on you. Run this yourself every time you change
`config/tasks.toml`, and commit the result together with the config:

```powershell
.\.venv\Scripts\python.exe scripts\generate_workflows.py
```

macOS:

```bash
./.venv/bin/python scripts/generate_workflows.py
```

Forgetting is the failure mode worth understanding, because nothing breaks
loudly. The config and the workflows simply drift: GitHub keeps running the old
generated YAML, so a new cron time, a renamed script, or a new
`workflow_dispatch` input silently does not take effect. The most confusing case
is the test slot, where `config/tasks.toml` says `is_test = false` but
`.github/workflows/test_workflow.yml` still holds a full copy of the task, leaving
it dispatchable from `main`.

The `Test Slot Guard` check on pull requests into `main` catches that specific
drift, but it only covers the test slot. Regenerating is still your job.

To check whether your working tree has drifted, regenerate and look at
`git status`. Clean output means you were in sync:

```powershell
.\.venv\Scripts\python.exe scripts\generate_workflows.py
git status --short
```

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
tasks can test fetch and transform logic without touching a Sheet.

`--skip-sheet` is required locally, not optional. Google Sheets access works only
inside GitHub Actions, where the workflow mints a short-lived service account
token. A local run that reaches `read_records_from_sheet` or
`write_records_to_sheet` fails with a clear error instead of contacting the API.
To exercise the real Sheet, push your branch and run the workflow.

#### Wiring `skip_sheet` Into Your Task

Do not branch on `settings.skip_sheet` yourself. Pass it to the Sheets helpers
and let them handle it, so the rest of your task runs identically either way:

```python
from edgerunner.sheets import read_records_from_sheet, write_records_to_sheet

def run(settings):
    source = read_records_from_sheet(
        spreadsheet_id=settings["source_sheet_id"],
        tab_name=settings["source_tab_name"],
        skip_sheet=settings.skip_sheet,
        mock_response=[{"date": "2026-08-01", "store": "store_a", "revenue": "140.00"}],
    )

    records = transform(source)

    rows = write_records_to_sheet(
        spreadsheet_id=settings.sheet_id,
        tab_name=settings.tab_name,
        records=records,
        write_mode=settings.get("sheet_write_mode", "replace"),
        skip_sheet=settings.skip_sheet,
    )

    return {"task": settings.name, "sheet_row_count": len(rows)}
```

What each helper does when `skip_sheet=True`:

- `read_records_from_sheet` returns `mock_response` without calling the API, or
  `[]` if you did not pass one. A fixture is worth writing: it lets your
  transform and filter logic run against realistically shaped rows locally.
  [`tasks/shared/google_sheet_to_sheet.py`](tasks/shared/google_sheet_to_sheet.py)
  builds its fixture dates relative to today, so its date-window filter both
  selects and rejects rows during a local run instead of passing an empty frame
  through untested.
- `write_records_to_sheet` skips the API call but still builds and returns the
  rows it would have written, as `list[list[Any]]` with the header row first. It
  returns those same rows on the real path too, so you get one shape of return
  value in both cases.

Both helpers still validate before skipping, so a bad `write_mode` or a missing
`upsert_key_columns` fails on your machine rather than in CI.

Both parameters default to off. Omitting them keeps the old behavior: the call
tries to reach the API and hits the GitHub Actions gate locally.

If a local run fails with the Sheets gate error even though you passed
`--skip-sheet`, the usual cause is a call site that does not forward it. The
error says so; check your `skip_sheet=settings.skip_sheet` arguments before
re-checking the command line.

The cloud path is deliberately unchanged. Generated workflows never pass
`--skip-sheet`, so GitHub Actions always uses the real API. There is no dry-run
switch in CI.

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

Open the Actions tab in GitHub and select the workflow. Use the branch dropdown
to choose your `testing-{description}` branch.

For an existing task, choose its generated workflow and click **Run workflow**.
For a scheduled task, GitHub runs it from the default branch according to
`cron_setting`, but you should still manually run it once from your testing
branch before merging.

For a **brand new** task, its generated workflow is not dispatchable yet. Use the
test workflow described below.

#### Testing A New Task From A Branch

**The problem.** GitHub only offers **Run workflow** for workflows that already
exist on the default branch. The workflow you just generated for your new task
lives only on your testing branch, so it does not appear in the Actions tab at
all. You cannot run it until it merges, which is backwards: you want to prove it
works *before* asking for review.

**The solution.** The framework keeps a permanent slot at
`.github/workflows/test_workflow.yml`. It is always generated, never deleted, and
always named `test workflow`, so it sits on the default branch forever and can be
dispatched against any branch. Setting `is_test = true` copies your task's steps
into it.

Full walkthrough:

**1. Point the slot at your task.** Add `is_test = true` to your task in
`config/tasks.toml`:

```toml
[[tasks]]
name = "my_job"
script_path = "tasks/my_client/my_job.py"
is_test = true
```

**2. Regenerate and commit.** With the pre-commit hook enabled, a normal commit
is enough, because staging `config/tasks.toml` triggers regeneration:

```powershell
git add config\tasks.toml tasks\my_client\my_job.py
git commit -m "Add my_job automation task"
```

Without the hook, regenerate first and stage the result too:

```powershell
.\.venv\Scripts\python.exe scripts\generate_workflows.py
git add config\tasks.toml tasks\my_client\my_job.py .github\workflows
git commit -m "Add my_job automation task"
```

Either way, confirm the slot picked up your task. The generator prints which task
it holds:

```text
Wrote .github\workflows\test_workflow.yml (holding my_job)
```

If it prints `(empty)` instead, `is_test = true` did not land in the config.

**3. Push the branch.**

```powershell
git push -u origin testing-my-job
```

**4. Run it.** Open the Actions tab, select **test workflow** in the left
sidebar, click **Run workflow**, and pick your `testing-{description}` branch in
the branch dropdown. GitHub reads the workflow file from the branch you select,
so it runs your task's steps: your `workflow_dispatch` inputs, GCP auth through
Workload Identity Federation, the real Sheets write, and Slack alerting.

**5. Check the run.** The slot is always named `test workflow`, so the run page
does not say which task it holds. Its first real step, `Report the task under
test`, prints that for you before the slower install and auth steps:

```text
## Task under test: `my_job`

Script: `tasks/my_client/my_job.py`
```

The same report is written to the run's **Summary** page, so you can confirm the
task and its settings without opening the log. It reads `config/tasks.toml` from
the branch you selected and applies your `workflow_dispatch` inputs, so the values
shown are the ones the task actually runs with. If the task name is not what you
expected, the slot was generated from a different config than the one you just
pushed.

After that, the usual checklist: green run, expected inputs and row counts in the
log, expected output in the target Sheet.

**6. Clear the slot before opening the PR.** Set `is_test = false` (or delete the
line), commit so the workflow regenerates, and push:

```text
Wrote .github\workflows\test_workflow.yml (empty)
```

When you open a pull request into `main`, the `Auto-clear Test Slot` workflow
also tries to do this cleanup for you: it sets any `is_test = true` entries back
to `false`, regenerates the test workflow, and pushes a small commit back to your
branch. It only runs automatically when the PR is opened, so later pushes to the
same PR can temporarily set `is_test = true` again for reviewer-requested
retests without being cleared immediately. After a retest, either clear the slot
manually or run the `Auto-clear Test Slot` workflow from the Actions tab with the
PR branch name as its `branch` input.

This is a convenience layer, not the source of truth. If branch protection or
repository settings do not allow workflows to push commits, the push step will
fail with Git's permission error. If the pull request comes from a fork, the
default `GITHUB_TOKEN` usually cannot write to the fork branch, so the automatic
cleanup may not run successfully. In those cases, clear the slot manually; the
`Test Slot Guard` check still catches anything left behind.

Notes and guardrails:

- **Only one task may set `is_test = true`.** Generation fails with an error
  naming every offending task, and the pre-commit hook runs the generator, so an
  ambiguous config cannot reach GitHub.
- **A pull request into `main` fails while the slot is loaded.** The `Test Slot
  Guard` workflow runs `scripts/check_test_slot_cleared.py`, which checks both
  the config and the generated file. That second check matters: turning off
  `is_test` without regenerating would leave a stale copy of your task
  dispatchable on `main`.
- **The slot never carries `cron_setting`.** It is manual only, so a scheduled
  task does not start firing twice per cron tick. The task's own generated
  workflow keeps the schedule.
- **`is_test` does not replace the task's own workflow.** Both are generated.
- **Do not delete `test_workflow.yml`.** The guard treats a missing slot as a
  failure, because deleting it from `main` breaks branch testing for everyone.

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
Google Sheet tab. It reads the configured `source_range` (or the full tab when omitted),
treats the first source row as headers, filters rows whose first column date falls between
the configured `start_date_offset` and `end_date_offset`, then writes the filtered pandas DataFrame to the target tab.

Update this entry in `config/tasks.toml` before running it:

```toml
[[tasks]]
name = "google_sheet_to_sheet"
script_path = "tasks/shared/google_sheet_to_sheet.py"
cron_setting = "40 12 * * *"
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

Run it locally to check the date filter and the rest of the script:

```powershell
.\.venv\Scripts\python.exe tasks\shared\google_sheet_to_sheet.py --google_sheet_to_sheet --skip-sheet
```

With `--skip-sheet` this task skips the source read as well as the target write,
so it runs against an empty frame and reports `source_record_count: 0`. Both ends
touch Sheets, and Sheets is reachable only from GitHub Actions. To move real data,
run the workflow:

```powershell
gh workflow run "shared / google_sheet_to_sheet"
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
default branch in `America/New_York`.

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
above. `error_log` contains only the final non-empty sanitized task log line on
failure and is empty on success. Use `run_url` to open the full GitHub Actions
run when deeper debugging is needed.

## Secrets In Task Scripts

For production, use a Secret Manager version address:

```python
from edgerunner.secrets import access_secret

token = access_secret("projects/YOUR_PROJECT_ID/secrets/YOUR_SECRET/versions/latest")
```

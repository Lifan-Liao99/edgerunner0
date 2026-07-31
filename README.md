# EdgeRunner Automation Tasks

This repo runs standalone Python automation scripts from GitHub Actions. Each
task is a complete script under `tasks/`: it can call APIs, transform data, use
`dlt`, write Google Sheets, trigger another service, or do any other custom
automation.

The main execution path is GitHub Actions. Local setup is only needed when you
want to edit or regenerate workflows from your machine.

## Project Shape

- `tasks/_template.py`: starting point to copy when adding a task.
- `tasks/jsonplaceholder_posts.py`: complete example task for a public posts API.
- `tasks/github_cpython_repo.py`: complete example task for GitHub's public API.
- `config/tasks.toml`: task metadata such as script path, cron, sheet id, and tab.
- `src/edgerunner/sheets.py`: small shared helper for writing records to Sheets.
- `src/edgerunner/secrets.py`: small shared helper for Secret Manager.
- `scripts/generate_workflows.py`: regenerates `.github/workflows/*.yml`.

## Local Setup

Install Python 3.11+ and create a virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e .
```

Run one task locally only if you want a quick manual check:

```powershell
.\.venv\Scripts\python.exe tasks\github_cpython_repo.py --task-name github_cpython_repo --skip-sheet
.\.venv\Scripts\python.exe tasks\github_cpython_repo.py --github_cpython_repo --skip-sheet
```

## Adding A Task

1. Copy `tasks/_template.py` to your own script, for example `tasks/my_job.py`.
   The template carries the standard `main()` shape, the settings access
   patterns, and the TOML entry that matches it.

```powershell
Copy-Item tasks\_template.py tasks\my_job.py
```

2. Add one entry to `config/tasks.toml`:

```toml
[[tasks]]
name = "my_job"
script_path = "tasks/my_job.py"
cron_setting = "12 4 * * *"
sheet_id = "YOUR_GOOGLE_SHEET_ID"
tab_name = "my_job"
gcp_auth = true
api_endpoint = "https://api.example.com/data"
api_timeout_seconds = 30
```

3. Regenerate workflows:

```powershell
.\.venv\Scripts\python.exe scripts\generate_workflows.py
```

The generated workflow runs:

```text
python tasks/my_job.py --task-name my_job
```

For local command-line use, every task script also accepts the shorthand
`--my_job` form:

```powershell
.\.venv\Scripts\python.exe tasks\my_job.py --my_job
```

So the script owns its arguments, API calls, transforms, dlt pipeline, and side
effects.

The same script can power multiple tasks. Add multiple TOML entries with
different `name` values and the same `script_path`; the workflow passes the
selected task name with `--task-name`, and the script loads that entry's
parameters.

Every key in a task's TOML entry is available to that Python script:

```python
from edgerunner.task_config import load_task_settings, parse_task_args

args = parse_task_args("Run my reusable automation script.")
settings = load_task_settings(args.task_name)

endpoint = settings["api_endpoint"]
timeout = settings.get("api_timeout_seconds", 30)
sheet_id = settings.sheet_id
tab_name = settings.tab_name
```

Known fields such as `name`, `script_path`, `cron_setting`, `sheet_id`,
`tab_name`, and `gcp_auth` have convenience properties. Custom fields are
preserved in `settings.params` and can be accessed with `settings["key"]`.

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
`workflow_dispatch`; the cron runs on the default branch in UTC.

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

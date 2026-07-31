# EdgeRunner Automation Tasks

This repo runs standalone Python automation scripts from GitHub Actions. Each
task is a complete script under `tasks/`: it can call APIs, transform data, use
`dlt`, write Google Sheets, trigger another service, or do any other custom
automation.

`config/tasks.toml` stores shared task metadata:

- task name
- Python script path
- cron setting
- sheet id
- tab name
- whether the task participates in local smoke tests
- whether the workflow should authenticate to Google Cloud

## Project Shape

- `tasks/jsonplaceholder_posts.py`: complete example task for a public posts API.
- `tasks/github_cpython_repo.py`: complete example task for GitHub's public API.
- `config/tasks.toml`: metadata for each task.
- `src/edgerunner/sheets.py`: small shared helper for writing records to Sheets.
- `src/edgerunner/secrets.py`: small shared helper for Secret Manager or `env:...`.
- `scripts/generate_workflows.py`: regenerates `.github/workflows/*.yml`.
- `scripts/run_local_tasks.py`: runs tasks marked `local_test = true`.

## Local Setup

Install Python 3.11+ and create a virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e .
```

If `py -3.11` is not available, install Python 3.11+ for Windows, reopen
PowerShell, and check:

```powershell
py -0p
```

## Local Runs

Run public API + dlt smoke tests without writing Google Sheets:

```powershell
.\.venv\Scripts\python.exe scripts\run_local_tasks.py --local-test
```

Local smoke tests pass `--use-sample-on-failure` to example scripts, so they can
still validate script structure and dlt loading when your network cannot reach a
public endpoint. GitHub Actions runs scripts without that flag.

Run local smoke tests and write Google Sheets:

```powershell
.\.venv\Scripts\python.exe scripts\run_local_tasks.py --local-test --write-sheet
```

Run one script directly:

```powershell
.\.venv\Scripts\python.exe tasks\jsonplaceholder_posts.py --skip-sheet --use-sample-on-failure
.\.venv\Scripts\python.exe tasks\github_cpython_repo.py
```

## Google User Login For Local Sheets

This repo does not require service account keys. If your organization enforces
`iam.disableServiceAccountKeyCreation`, keep that policy enabled.

Install Google Cloud CLI if `gcloud` is not available:

https://docs.cloud.google.com/sdk/docs/install-sdk

Enable these APIs in the GCP project:

- Google Sheets API
- Secret Manager API, only if a task reads real protected API secrets

Create local Application Default Credentials with your Google user:

```powershell
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/cloud-platform
```

If Google blocks the default app, create or use an organization-approved OAuth
Desktop Client and pass it to `gcloud`:

```powershell
gcloud auth application-default login --client-id-file="C:\Users\Lifan Liao\Desktop\oauth-client.json" --scopes=https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/cloud-platform
```

Your Google user needs:

- edit access to the target Google Sheet
- `roles/secretmanager.secretAccessor`, only for tasks that read Secret Manager

Put the sheet id in `.env`:

```text
GOOGLE_SHEET_ID=your_google_sheet_id
```

For this repo's checked-in examples, the Sheet ID is stored directly in
`config/tasks.toml`. Use `env:GOOGLE_SHEET_ID` only if you want to keep a Sheet
ID out of the repo.

## Adding A Task

1. Create a complete Python script in `tasks/`, for example `tasks/my_job.py`.
2. Add one entry to `config/tasks.toml`:

```toml
[[tasks]]
name = "my_job"
script_path = "tasks/my_job.py"
cron_setting = "12 4 * * *"
sheet_id = "env:GOOGLE_SHEET_ID"
tab_name = "my_job"
local_test = true
gcp_auth = true
```

3. Regenerate workflows:

```powershell
.\.venv\Scripts\python.exe scripts\generate_workflows.py
```

The generated workflow runs:

```text
python tasks/my_job.py
```

So the script owns its arguments, API calls, transforms, dlt pipeline, and side
effects.

## GitHub Actions Auth

GitHub Actions should stay keyless via Workload Identity Federation. Add these
repository secrets:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`

Each generated workflow has exactly one job and can be run manually with
`workflow_dispatch`.

### Set Up GitHub WIF

These commands configure GitHub Actions from this repo,
`Lifan-Liao99/edgerunner0`, to impersonate a Google service account in the
`edgerunner-504102` GCP project.

Before running them, make sure your active `gcloud` account can administer IAM
in the project:

```powershell
gcloud auth list
gcloud projects describe edgerunner-504102
```

The account running setup needs these project roles, or an administrator can run
the setup commands for you:

- `roles/serviceusage.serviceUsageAdmin`, to enable required APIs
- `roles/iam.serviceAccountAdmin`, to create the GitHub Actions service account
- `roles/iam.workloadIdentityPoolAdmin`, to create the WIF pool and provider

If you see `AUTH_PERMISSION_DENIED`, `iam.serviceAccounts.create denied`, or
`iam.workloadIdentityPools.create denied`, your account does not have enough
permission on the project or the project ID is not one you can access.

```powershell
$PROJECT_ID = "edgerunner-504102"
$REPO = "Lifan-Liao99/edgerunner0"
$POOL_ID = "github"
$PROVIDER_ID = "edgerunner0"
$SA_NAME = "edgerunner-actions"
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
  --display-name="edgerunner0 GitHub provider" `
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

Add the printed values to GitHub repository secrets:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`

Then share the target Google Sheet with the service account email:

```text
edgerunner-actions@edgerunner-504102.iam.gserviceaccount.com
```

Give it Editor access on the sheet. Google Sheets permissions are controlled by
sharing the spreadsheet, not by a GCP IAM role.

If a task reads Google Secret Manager secrets, also grant the service account
access to those secrets:

```powershell
gcloud secrets add-iam-policy-binding YOUR_SECRET_NAME `
  --project=$PROJECT_ID `
  --role="roles/secretmanager.secretAccessor" `
  --member="serviceAccount:$SA_EMAIL"
```

## Secrets In Task Scripts

For local-only testing, use environment variables:

```python
from edgerunner.secrets import access_secret

token = access_secret("env:EXAMPLE_API_TOKEN")
```

For production, use a Secret Manager version address:

```python
token = access_secret("projects/YOUR_PROJECT_ID/secrets/YOUR_SECRET/versions/latest")
```

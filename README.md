# Repo template

## Requirements

- Python {{ python_version }}
- [`gcloud` CLI](https://cloud.google.com/sdk/docs/install) — authenticated via `gcloud auth login`

## Getting started

1. Create an empty repository on GitHub and clone it locally:
   ```bash
   git clone <your-repo-url>
   cd <your-repo-name>
   ```
2. Install [Copier](https://copier.readthedocs.io/en/stable/) if you don't have it:
   ```bash
   pip install copier
   ```
3. Scaffold the project from this template:
   ```bash
   copier copy gh:kdrivas/repo-tmp .
   ```
4. Authenticate with Google Cloud:
   ```bash
   gcloud auth login
   gcloud auth application-default login
   ```
5. Install `uv` and `just`:
   ```bash
   bash scripts/install_tools.sh
   ```
6. Install project dependencies:
   ```bash
   just install
   ```
7. Set up pre-commit hooks:
   ```bash
   just setup-hooks
   ```
8. Initialize the secrets baseline:
   ```bash
   uv run detect-secrets scan > .secrets.baseline
   ```

## Pipelines

This project uses [Flyte](https://flyte.org/) and [`mlops-lib`](https://github.com/paccar/aacoe-mlops-observability-lib/) to define and run ML pipelines.

The included example is `CompletePipeline` — a full regression workflow: ingestion → preprocess → split → postprocess → model selection → train → evaluate. Use it as a starting point and replace it with your own logic.

To run it locally:

```bash
just docker-build
uv run mlops_lib generate_pipeline_config {{ package_name }}/pipelines/complete_pipeline.py complete_pipeline -o pipelines/complete_pipeline.yaml
uv run mlops_lib run_pipeline pipelines/complete_pipeline.yaml --mode local
```

To run it on Cloud Run Jobs:

```bash
# 1. Build the Docker image and push it to Artifact Registry
# Note: Artifact Registry repository names do not allow underscores — use hyphens instead
#       e.g. if package_name is "fraud_new", the GAR repo must be "fraud-new"
GCP_PROJECT_ID=<your-gcp-project-id> ARTIFACT_REGISTRY_REPO=<gar-repo-name> ./scripts/build_and_push.sh

# 2. Execute the pipeline
uv run mlops_lib run_pipeline pipelines/complete_pipeline.yaml \
  --mode cloud_run_job \
  --gcp-project <your-gcp-project-id> \
  --job-name {{ package_name }}-pipeline \
  --image us-central1-docker.pkg.dev/<your-gcp-project-id>/<gar-repo-name>/{{ package_name }}:latest
```

## Adding a new pipeline

1. Create `{{ package_name }}/pipelines/my_pipeline.py` implementing `FlytePipeline`.
2. Iterate by running it directly — recommended during development since it skips YAML generation:
   ```bash
   uv run python -m {{ package_name }}.pipelines.my_pipeline
   ```
3. Once ready, build the Docker image (referenced by pipelines at runtime):
   ```bash
   just docker-build
   ```
4. Generate its YAML config:
   ```bash
   uv run mlops_lib generate_pipeline_config {{ package_name }}/pipelines/my_pipeline.py my_pipeline -o pipelines/my_pipeline.yaml
   ```
5. Run it:
   ```bash
   uv run mlops_lib run_pipeline pipelines/my_pipeline.yaml --mode local
   ```

## Keeping your project up to date

```bash
git add . && git commit -m "chore: sync before template update"
copier update
```

Copier applies template changes while preserving your source code, tests, and pipeline configs. Conflicts are resolved interactively.

> Your setup answers are stored in `.copier-answers.yml` — Copier uses this to track the template version.

## Reference

### Commands

```bash
just install             # Install project dependencies
just test                # Run tests
just test-coverage       # Run tests with coverage report (≥ 60 %)
just lint                # Check linting
just lint-fix            # Auto-fix lint issues
just format              # Format code
just check-all           # Run all quality checks
just docker-build        # Build the Docker image
just docker-build-amd64  # Build for linux/amd64 (GCP deployment)
just docker-run          # Run the container (loads .env if present)
just cloud-deploy        # Build, push to GAR, and create/update the Cloud Run Job
just cloud-run           # Execute a pipeline on Cloud Run Jobs (default: complete_pipeline.yaml)
```

### Automations

The following checks run automatically via pre-commit hooks and CI:

| Automation                  | Tool            | Trigger         |
| --------------------------- | --------------- | --------------- |
| Linting & formatting        | Ruff            | pre-commit + CI |
| Type checking               | Basedpyright    | pre-commit + CI |
| Docstring coverage (≥ 80 %) | docstr-coverage | pre-commit + CI |
| Test coverage (≥ 60 %)      | pytest-cov      | pre-commit + CI |
| Secret scanning             | detect-secrets  | pre-commit      |
| Notebook output stripping   | nbstripout      | pre-commit      |
| PR style validation         | GitHub Actions  | on PR open/edit |

### Project structure

```
.
├── {{ package_name }}/             # Main source package
│   ├── pipelines/                  # Pipeline definitions (one file per pipeline)
│   │   └── complete_pipeline.py
│   └── data.py                     # Dataset generation utilities
│
├── pipelines/                      # Generated YAML configs for each pipeline
│   └── complete_pipeline.yaml
│
├── tests/                          # Unit and integration tests
├── notebooks/                      # Exploratory notebooks
├── docs/                           # Project documentation
├── infrastructure/                 # Dockerfile and build config
├── scripts/                        # Utility scripts (install_tools.sh, …)
│
├── justfile                        # Task runner (install, run, test, lint, …)
├── pyproject.toml                  # Project metadata and dependencies
├── ruff.toml                       # Linter/formatter configuration
└── pyrightconfig.json              # Type checker configuration
```

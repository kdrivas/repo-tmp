# MLOps Repo Template

Template project for building ML pipelines with `mlops_lib` (aacoe-mlops-observability-lib), Flyte, and MLflow.

## Requirements

- Python 3.12
- `gcloud` CLI authenticated (`gcloud auth login`)

## Installation

**1. Install `uv`, `just`, and project dependencies** in one step:

```bash
bash install_dependencies.sh
```

The script installs `uv` and `just` if not already present, runs `just install`, then removes itself.

**2. Set up pre-commit hooks:**

```bash
just setup-hooks
```

## Usage

### Generate a pipeline YAML config

```bash
just pipeline-yaml src/pipelines/complete_pipeline.py CompletePipeline
# → generates pipelines/complete_pipeline.yaml
```

### Run a pipeline locally

```bash
just pipeline-run pipelines/complete_pipeline.yaml
```

Target options: `local` (default), `remote`.

```bash
just pipeline-run pipelines/complete_pipeline.yaml remote
```

### Other commands

```bash
just install           # Install project dependencies
just test              # Run tests
just test-coverage     # Run tests with coverage report
just lint              # Check linting
just lint-fix          # Auto-fix lint issues
just format            # Format code
just check-all         # Run all quality checks
just docker-build      # Build Docker image
```

## Project structure

```
.
├── src/                        # Main source package
│   ├── pipelines/              # Pipeline definitions (one file per pipeline)
│   │   ├── complete_pipeline.py
│   │   └── simplified_pipeline.py
│   ├── data.py                 # Dataset generation utilities
│   └── utils.py                # Shared helpers (I/O, model persistence)
│
├── pipelines/                  # Generated YAML configs for each pipeline
│   ├── complete_pipeline.yaml
│   └── simplified_pipeline.yaml
│
├── tests/                      # Unit and integration tests
├── notebooks/                  # Exploratory notebooks
├── docs/                       # Project documentation (MkDocs)
├── infrastructure/             # Dockerfile and build config
│
├── justfile                    # Task runner (install, run, test, lint, …)
├── pyproject.toml              # Project metadata and dependencies
├── ruff.toml                   # Linter/formatter configuration
└── pyrightconfig.json          # Type checker configuration
```

## Adding a new pipeline

1. Create `src/pipelines/my_pipeline.py` implementing `FlytePipeline`.
2. Generate its YAML config:
   ```bash
   just pipeline-yaml src/pipelines/my_pipeline.py MyPipeline
   ```
3. Run it:
   ```bash
   just pipeline-run pipelines/my_pipeline.yaml
   ```

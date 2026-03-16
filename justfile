SRC := 'src'

# Show available commands
default:
  just --list

# Install project dependencies
install:
  uv sync --all-groups

# Remove virtual environment and reinstall dependencies
reinstall:
  rm -rf .venv
  uv sync --all-groups

# Setup pre-commit hooks for all hook types found in .pre-commit-config.yaml
setup-hooks:
  #!/usr/bin/env bash
  set -euo pipefail
  # Extract unique hook types from .pre-commit-config.yaml and install each
  hook_types=$(uv run python "{{justfile_directory()}}/scripts/extract_necessary_pre_commit_types.py")

  if [ -z "$hook_types" ]; then
    echo "No stages defined in hooks, using default pre-commit installation..."
    uv run pre-commit install
  else
    echo "Found hook types: $hook_types"
    for hook_type in $hook_types; do
      echo "Installing $hook_type hooks..."
      uv run pre-commit install --hook-type "$hook_type" || true
    done
  fi

# Run tests
test:
  uv run pytest

# Run tests with coverage report
test-coverage:
  uv run pytest --cov={{SRC}} --cov-fail-under=60

# Run linter to check for issues
lint:
  uv run ruff check

# Run linter and automatically fix issues
lint-fix:
  uv run ruff check --fix

# Run type checker
check-types:
  uv run basedpyright {{SRC}}/

# Check code formatting without making changes
check-format:
  uv run ruff format --check

# Format code automatically
format:
  uv run ruff format

# Check docstring coverage
docstring-coverage:
  uv run docstr-coverage --fail-under 80 --verbose=2 --skip-file-doc --skip-init {{SRC}}

# Clean build artifacts and cache files
clean:
  find . -type f -name "*.pyc" -delete
  find . -type d -name "__pycache__" -exec rm -rf {} +
  find . -type d -name "*.egg-info" -exec rm -rf {} +
  find . -type f -name ".coverage" -delete
  find . -type d -name "htmlcov" -exec rm -rf {} +
  find . -type d -name ".pytest_cache" -exec rm -rf {} +
  find . -type d -name ".mypy_cache" -exec rm -rf {} +
  find . -type d -name "dist" -exec rm -rf {} +
  find . -type d -name "build" -exec rm -rf {} +

# Update all dependencies to latest versions
dependency-update:
  uv lock --upgrade && uv sync --all-groups

# Show dependency tree
dependency-tree:
  uv tree

# Show outdated dependencies
dependency-outdated:
  uv pip list --outdated

# Run all quality checks
check-all: lint check-types check-format test-coverage docstring-coverage

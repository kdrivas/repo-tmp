#!/usr/bin/env bash
set -euo pipefail

# Install uv
if ! command -v uv &>/dev/null; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.cargo/bin:$PATH"
else
  echo "uv already installed: $(uv --version)"
fi

# Install just
if ! command -v just &>/dev/null; then
  echo "Installing just..."
  curl -LsSf https://just.systems/install.sh | bash -s -- --to "$HOME/.local/bin"
  export PATH="$HOME/.local/bin:$PATH"
else
  echo "just already installed: $(just --version)"
fi

# Verify gcloud authentication
if ! gcloud auth print-access-token &>/dev/null; then
  echo "Error: not authenticated with gcloud. Run 'gcloud auth login' and try again."
  exit 1
fi

# Run project install
just install

# Set up pre-commit hooks
echo "Setting up pre-commit hooks..."
just setup-hooks

# Initialize the detect-secrets baseline
echo "Initializing secrets baseline..."
uv run detect-secrets scan > .secrets.baseline

# Self-remove
rm -- "$0"

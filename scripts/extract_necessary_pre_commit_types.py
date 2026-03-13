"""Extract all unique stages from a pre-commit configuration file.

If ran directly, prints the stages to stdout, space-separated. If no stages are found, prints
an empty string.
"""

from __future__ import annotations

from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from enum import StrEnum
    from typing import TypedDict

    class Stage(StrEnum):
        """Possible spots to run a git hook."""

        COMMIT_MESSAGE = "commit-msg"
        POST_CHECKOUT = "post-checkout"
        POST_COMMIT = "post-commit"
        POST_MERGE = "post-merge"
        POST_REWRITE = "post-rewrite"
        PRE_COMMIT = "pre-commit"
        PRE_MERGE_COMMIT = "pre-merge-commit"
        PRE_PUSH = "pre-push"
        PRE_REBASE = "pre-rebase"
        PREPARE_COMMIT_MSG = "prepare-commit-msg"

    class Hook(TypedDict, total=False):
        """Represents a pre-commit hook configuration.

        Full: https://pre-commit.com/#pre-commit-configyaml---hooks
        """

        id: str
        stages: list[Stage]

    class Repo(TypedDict, total=False):
        """Represents a pre-commit repo (a collection of hooks)."""

        repo: str
        hooks: list[Hook]

    class Config(TypedDict, total=False):
        """Schema for `.pre-commit-config.yaml`."""

        repos: list[Repo]


def parse_arguments() -> Namespace:
    """Parse command line arguments."""
    parser = ArgumentParser(
        description="Extract all necessary pre-commit stages from .pre-commit-config.yaml",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )

    default_config_path = Path(__file__).parents[1] / ".pre-commit-config.yaml"
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path,
        help="Path to the pre-commit configuration file.",
    )
    return parser.parse_args()


def extract_stages(config_file: Path) -> set[str]:
    """Extract all unique stages from a pre-commit configuration file.

    Args:
        config_file (Path): Path to the pre-commit configuration file.

    Returns:
        set[str]: A set of unique stages found in the configuration. If no hook contains a `stage`
            key, returns an empty set.
    """
    with open(config_file) as cf:
        config: Config = yaml.safe_load(cf)

    return {
        stage
        for repo in config.get("repos", [])
        for hook in repo.get("hooks", [])
        for stage in hook.get("stages", [])
    }


if __name__ == "__main__":
    args = parse_arguments()
    stages = extract_stages(args.config)
    print(" ".join(sorted(stages)))  # noqa: T201 we want to output to stdout.

"""Entry point to run the dummy pipelines locally.

Usage:
    python -m src.pipelines.run
"""

import logging

from mlops_lib.pipelines.flyte import FlyteRunner

from src.pipelines.complete_pipeline import complete_pipeline
from src.pipelines.simplified_pipeline import simplified_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)

logger = logging.getLogger(__name__)

runner = FlyteRunner(target="local")


def run_simplified() -> None:
    """Run the simplified pipeline (ingestion, split, train, evaluate) locally."""
    logger.info("Running simplified pipeline...")
    result = runner.run(simplified_pipeline, version="v0.1")
    logger.info("Simplified result: %s", result)


def run_complete() -> None:
    """Run the complete pipeline (all steps) locally."""
    logger.info("Running complete pipeline...")
    result = runner.run(complete_pipeline, version="v0.1")
    logger.info("Complete result: %s", result)


def main() -> None:
    """Run all pipelines."""
    run_simplified()
    run_complete()


if __name__ == "__main__":
    main()

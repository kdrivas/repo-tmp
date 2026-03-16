"""Pipeline entry point.

Usage:
    python -m src.run
"""

import logging

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )
    logger.info("Pipeline started.")


if __name__ == "__main__":
    main()

"""Path constants for easy file access throughout the project.

This module provides standardized path constants that can be used to access
files and directories relative to the repository root and package location.
All paths are absolute and work regardless of the current working directory.
"""

from pathlib import Path

_THIS_FILE = Path(__file__)

PACKAGE = _THIS_FILE.parent
"""Path to the package directory containing the main project code."""

ROOT = PACKAGE.parent
"""Path to the repository root directory."""

TESTS = ROOT / "tests"
"""Path to the tests directory."""

SCRIPTS = ROOT / "scripts"
"""Path to the scripts directory."""

DOCS = ROOT / "docs"
"""Path to the documentation directory."""

DATA = ROOT / "data"
"""Path to the data directory for storing project data files."""

LOGS = ROOT / "logs"
"""Path to the logs directory for storing application logs."""

NOTEBOOKS = ROOT / "notebooks"
"""Path to the notebooks directory for storing Jupyter notebooks."""

__all__ = [
    "DATA",
    "DOCS",
    "LOGS",
    "NOTEBOOKS",
    "PACKAGE",
    "ROOT",
    "SCRIPTS",
    "TESTS",
]

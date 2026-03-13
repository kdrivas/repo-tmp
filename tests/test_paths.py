"""Tests for the paths module."""

from pathlib import Path

from src.constants import PACKAGE_NAME
from src.paths import DATA, DOCS, LOGS, NOTEBOOKS, PACKAGE, ROOT, SCRIPTS, TESTS


def test_package_path() -> None:
    """Test that PACKAGE points to the correct package directory."""
    # PACKAGE should point to the project_base directory
    assert PACKAGE.name == "src"
    assert PACKAGE.is_dir()
    assert (PACKAGE / "__init__.py").exists()


def test_package_name() -> None:
    """Test that PACKAGE_NAME matches the package directory name."""
    assert PACKAGE.name == PACKAGE_NAME
    assert PACKAGE_NAME == "src"


def test_root_path() -> None:
    """Test that ROOT points to the repository root."""
    # ROOT should be the parent of the package directory
    assert PACKAGE.parent == ROOT
    assert ROOT.is_dir()
    # The root should contain key template files
    assert (ROOT / "pyproject.toml").exists()
    assert (ROOT / ".gitignore").exists()


def test_tests_path() -> None:
    """Test that TESTS points to the tests directory."""
    assert TESTS == ROOT / "tests"
    assert TESTS.is_dir()


def test_scripts_path() -> None:
    """Test that SCRIPTS points to the scripts directory."""
    assert SCRIPTS == ROOT / "scripts"
    assert SCRIPTS.is_dir()


def test_docs_path() -> None:
    """Test that DOCS points to the docs directory."""
    assert DOCS == ROOT / "docs"
    assert DOCS.is_dir()


def test_data_logs_paths() -> None:
    """Test that optional paths are properly constructed."""
    # These directories might not exist but should be proper Path objects
    assert isinstance(DATA, Path)
    assert isinstance(LOGS, Path)
    assert isinstance(NOTEBOOKS, Path)

    # They should be relative to ROOT
    assert DATA == ROOT / "data"
    assert LOGS == ROOT / "logs"
    assert NOTEBOOKS == ROOT / "notebooks"


def test_all_paths_are_pathlib_paths() -> None:
    """Test that all exported constants are Path objects."""
    paths = [PACKAGE, ROOT, TESTS, SCRIPTS, DOCS, DATA, LOGS, NOTEBOOKS]
    for path in paths:
        assert isinstance(path, Path), f"{path} is not a Path object"


def test_all_paths_are_absolute() -> None:
    """Test that all provided paths are absolute."""
    paths = [PACKAGE, ROOT, TESTS, SCRIPTS, DOCS, DATA, LOGS, NOTEBOOKS]
    for path in paths:
        assert path.is_absolute(), f"{path} is not an absolute path"


def test_relative_imports_work() -> None:
    """Test that the paths can be used for relative imports within the package."""
    # Test that we can construct paths relative to PACKAGE
    src_file = PACKAGE / "src.py"
    assert src_file.exists()

    paths_file = PACKAGE / "paths.py"
    assert paths_file.exists()

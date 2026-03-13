# /// script
# dependencies = [
#     "tomlkit",
# ]
# ///
"""Script to replace sections of a target TOML file with sections from a source TOML file."""

# tomlkit typehints are quite bad so we need to disable unknown type checks.
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
import argparse
import sys
from collections.abc import Iterator, MutableMapping
from copy import deepcopy
from pathlib import Path
from typing import NamedTuple, TypeGuard, cast

from tomlkit import TOMLDocument, dumps, parse
from tomlkit import table as make_table
from tomlkit.container import OutOfOrderTableProxy
from tomlkit.items import Table

TableLike = Table | OutOfOrderTableProxy


def is_table_like(value: object) -> TypeGuard[TableLike]:
    """Check if a value is a table-like object (Table or OutOfOrderTableProxy)."""
    return isinstance(value, TableLike)


def find_sections(
    table: TOMLDocument | TableLike, path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], TableLike]]:
    """Recursively find all concrete configuration sections in a TOML table.

    A "concrete section" is a table that contains at least one non-table value (i.e., strings,
    numbers, lists). These are the actual configuration sections like `[tool.pyright]` or
    `[tool.ruff.lint]` that hold settings, as opposed to intermediate parent tables like `[tool]`
    which only contain nested tables.

    Args:
        table: The TOML table to search through.
        path: The current path as a tuple of keys (i.e., `('tool', 'ruff', 'lint')`).

    Yields:
        Tuples of (path, table) where:
            - path: A tuple of keys representing the section's location.
            - table: The `TableLike` object containing the configuration values.

    Example:
        Given a TOML structure like:
            [tool.ruff]
            line-length = 88

            [tool.ruff.lint]
            select = ["E", "F"]

        This yields:
            (('tool', 'ruff'), <Table with line-length>)
            (('tool', 'ruff', 'lint'), <Table with select>)
    """
    has_non_table_value = any(not is_table_like(value) for value in table.values())
    if has_non_table_value and path:  # Only yield if we're not at the root
        # This is a concrete config section we should replace entirely.
        # Cast to TableLike since we know it's not a root TOMLDocument at this point
        yield path, cast(TableLike, table)

    # Recurse into child tables
    for key, value in table.items():
        if is_table_like(value):
            yield from find_sections(value, (*path, cast(str, key)))


def ensure_path(root: TOMLDocument, path: tuple[str, ...]) -> TableLike:
    """Make sure all parent tables along 'path' exist in root and return the table at 'path'."""
    # Handle empty path - return the root document itself (which acts as a Table)
    if not path:
        return cast(TableLike, root)

    current: MutableMapping[str, object] = root
    for key in path:
        # Only check membership first to avoid indexing errors
        if key not in current or not is_table_like(current[key]):
            current[key] = make_table()

        value = current[key]
        if not is_table_like(value):
            message = f"Expected table at path {path}, found {type(value)}."
            raise TypeError(message)
        current = cast(MutableMapping[str, object], value)  # Step into the path.

    if not is_table_like(current):
        message = f"Expected table at path {path}, found {type(current)}."
        raise TypeError(message)

    return current


def merge_source_into_target(target: TOMLDocument, source: TOMLDocument) -> TOMLDocument:
    """Merge sections from source TOML into target TOML.

    Only leaf values (non-table values) from source sections are merged into the target. This
    preserves any keys in the target that don't exist in the source.

    Args:
        target: The target TOML document to modify.
        source: The source TOML document to pull sections from.

    Returns:
        A copy of the original TOML, but with sections merged from source.
    """
    target = deepcopy(target)  # Avoid mutating the original target.
    # For each section in source, merge into the same section in target
    for path, section_table in find_sections(source):
        if not path:
            # Root-level primitive values (rare); skip for safety.
            continue

        parent_path, last_key = path[:-1], path[-1]
        parent_table = ensure_path(target, parent_path)

        # Merge: create section if it doesn't exist, then update with source values
        if last_key not in parent_table or not is_table_like(parent_table[last_key]):
            parent_table[last_key] = make_table()

        target_section = parent_table[last_key]
        if not is_table_like(target_section):
            message = f"Expected table at {'.'.join(path)}, found {type(target_section)}."
            raise TypeError(message)

        # Only merge leaf values (non-table values) from source.
        for key in section_table:
            value = section_table[key]
            if is_table_like(value):
                # Skip nested tables - they'll be handled in their own iteration
                continue

            # Get the full Item with comments/trivia if available (only Table has .item())
            source_item = section_table.item(key) if isinstance(section_table, Table) else value

            if key in target_section:
                # Replace in-place to preserve ordering
                if isinstance(target_section, Table):
                    # Use _value to keep comments intact.
                    target_section._value[key] = source_item  # type: ignore[reportAttributeAccessIssue] # noqa: SLF001
                else:
                    # For OutOfOrderTableProxy, just assign directly
                    target_section[key] = value
            else:
                target_section[key] = value
    return target


def modify_target_with_source(target_path: Path, source_toml_content: str) -> None:
    """Modify the target TOML file by merging sections from the source TOML file.

    Args:
        target_path: Path to the target TOML file.
        source_toml_content: Content of the source TOML file.
    """
    target = parse(target_path.read_text(encoding="utf-8"))
    source = parse(source_toml_content)

    modified_target = merge_source_into_target(target, source)

    target_path.write_text(dumps(modified_target), encoding="utf-8")


class ParsedArguments(NamedTuple):
    """Parsed and processed arguments ready for use."""

    target: Path
    source_toml_content: str


def parse_arguments() -> ParsedArguments:
    """Parse CLI arguments and return the Namespace."""
    parser = argparse.ArgumentParser(
        description=(
            "Merge TOML sections from a source file into a target TOML file while preserving "
            "comments and formatting. "
            "Values that exist only in the target file are kept, new values from the source "
            "are added and values that exist in both are overwritten in the target with values "
            "from the source."
        ),
        epilog=(
            "If --source is not provided, the script looks for input from a pipe (stdin).\n"
            "Example: cat update.toml | python script.py --target config.toml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--target",
        type=Path,
        help="Path to the target TOML file where replacements will be made",
        metavar="FILE",
        required=True,
    )
    parser.add_argument(
        "--source",
        type=Path,
        nargs="?",
        help=(
            "Path to the source TOML file containing sections to merge. If not provided, reads "
            "from stdin"
        ),
        metavar="FILE",
        required=False,
    )

    arguments = parser.parse_args()

    if arguments.source:  # User provided a file path argument
        contents = arguments.source.read_text(encoding="utf-8")
    elif not sys.stdin.isatty():  # Read piped data (since no path was given)
        contents: str = sys.stdin.read()
    else:  # No file path and no pipe (User just ran `python script.py`)
        parser.print_help()
        sys.exit(1)

    return ParsedArguments(
        target=arguments.target,
        source_toml_content=contents,
    )


if __name__ == "__main__":
    arguments = parse_arguments()
    modify_target_with_source(arguments.target, arguments.source_toml_content)

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "radon",
#     "rich",
# ]
# ///
"""Calculate and compare code complexity metrics using radon.

Run with `uv run scripts/code_complexity_metrics.py --help`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from statistics import StatisticsError, fmean
from typing import TYPE_CHECKING, Any, NamedTuple, TypedDict, cast

from rich.console import Console, Group, RenderableType
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from collections.abc import Iterable

# Analysis thresholds
HIGH_COMPLEXITY_THRESHOLD = 10.0
MODERATE_COMPLEXITY_THRESHOLD = 5.0
LOW_MAINTAINABILITY_THRESHOLD = 20.0
MODERATE_MAINTAINABILITY_THRESHOLD = 50.0
HIGH_DIFFICULTY_THRESHOLD = 20.0
SIGNIFICANT_LOC_INCREASE_FACTOR = 1.2
MIN_PERCENT_CHANGE_THRESHOLD = 1.0


class OutputFormat(StrEnum):
    """Output format options."""

    RICH = "rich"
    RAW = "raw"


class ComplexityAnalysisData(TypedDict):
    """Type definition for complexity analysis data."""

    target: float
    pr: float
    change: str
    warnings: list[str]


class MaintainabilityAnalysisData(TypedDict):
    """Type definition for maintainability analysis data."""

    target_average: float
    pr_average: float
    change: str
    min_mi: float
    warnings: list[str]


class HalsteadAnalysisData(TypedDict):
    """Type definition for Halstead metrics analysis data."""

    volume: str
    difficulty: str
    effort: str
    delivered_bugs: str
    warnings: list[str]


class LOCAnalysisData(TypedDict):
    """Type definition for lines of code analysis data."""

    target: int
    pr: int
    change: str
    warnings: list[str]


class ReportMetadataData(TypedDict):
    """Type definition for report metadata."""

    analysis_disclaimer: str


class CompleteReportData(TypedDict):
    """Type definition for complete report data."""

    cyclomatic_complexity: ComplexityAnalysisData
    maintainability_index: MaintainabilityAnalysisData
    lines_of_code: LOCAnalysisData
    halstead_metrics: HalsteadAnalysisData
    metadata: ReportMetadataData


class MaintainabilityMetrics(NamedTuple):
    """Container for maintainability metrics."""

    average: float
    minimum: float


class HalsteadMetrics(NamedTuple):
    """Container for Halstead metrics."""

    volume: float
    difficulty: float
    effort: float
    bugs: float


@dataclass
class CodeMetrics:
    """Container for all code metrics."""

    average_complexity: float = 0.0
    average_maintainability: float = 0.0
    min_maintainability: float = 0.0
    total_loc: int = 0
    average_halstead_volume: float = 0.0
    average_halstead_difficulty: float = 0.0
    average_halstead_effort: float = 0.0
    average_halstead_bugs: float = 0.0


class RadonMetricsCollector:
    """Collects and parses radon metrics from JSON output."""

    def __init__(self, target_dir: str = ".") -> None:
        self.target_dir = target_dir

    def _run_radon_command(self, command: str) -> dict[str, Any]:
        """Run a radon command and return parsed JSON output."""
        parts = ["radon", command, self.target_dir, "--json"]
        if command == "cc":
            parts.extend(["--show-complexity", "--average"])
        elif command == "mi":
            parts.extend(["--show-complexity"])

        try:
            result = subprocess.run(parts, capture_output=True, text=True, check=True)
            output = result.stdout.strip()
            return json.loads(output) if output else {}
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return {}

    def _safe_average(self, values: Iterable[float]) -> float:
        """Calculate average, returning 0.0 for empty iterables."""
        try:
            return fmean(values)
        except StatisticsError:
            return 0.0

    def collect_metrics(self) -> dict[str, dict[str, Any]]:
        """Collect all metrics and return structured data."""
        complexity_data = self._run_radon_command("cc")
        maintainability_data = self._run_radon_command("mi")
        halstead_data = self._run_radon_command("hal")
        raw_data = self._run_radon_command("raw")

        return {
            "code_complexity": complexity_data,
            "maintainability": maintainability_data,
            "halstead": halstead_data,
            "raw_metrics": raw_data,
        }

    def _parse_complexity_metrics(self, raw_metrics: dict[str, Any]) -> float:
        """Parse complexity metrics and return average complexity."""
        complexity_data = raw_metrics.get("code_complexity", {})
        if not complexity_data:
            return 0.0

        all_complexities: list[float] = [
            item["complexity"]
            for file_data in complexity_data.values()
            if isinstance(file_data, list)
            for item in file_data  # type: ignore[reportUnknownVariableType]; type is checked below.
            if isinstance(item, dict) and "complexity" in item
        ]

        return self._safe_average(all_complexities)

    def _parse_maintainability_metrics(self, raw_metrics: dict[str, Any]) -> MaintainabilityMetrics:
        """Parse maintainability metrics and return MaintainabilityMetrics."""
        maintainability_data = raw_metrics.get("maintainability", {})
        if not maintainability_data:
            return MaintainabilityMetrics(0.0, 0.0)

        mi_values: list[float] = [
            file_data["mi"]
            for file_data in maintainability_data.values()
            if isinstance(file_data, dict) and "mi" in file_data
        ]

        return MaintainabilityMetrics(
            self._safe_average(mi_values), min(mi_values) if mi_values else 0.0
        )

    def _parse_halstead_metrics(self, raw_metrics: dict[str, Any]) -> HalsteadMetrics:
        """Parse Halstead metrics and return HalsteadMetrics."""
        halstead_data = raw_metrics.get("halstead", {})
        if not halstead_data:
            return HalsteadMetrics(0.0, 0.0, 0.0, 0.0)

        volumes: list[float] = []
        difficulties: list[float] = []
        efforts: list[float] = []
        bugs: list[float] = []

        for file_data in halstead_data.values():
            if isinstance(file_data, dict) and "total" in file_data:
                total_data = cast(dict[str, float], file_data["total"])
                if "volume" in total_data:
                    volumes.append(total_data["volume"])
                if "difficulty" in total_data:
                    difficulties.append(total_data["difficulty"])
                if "effort" in total_data:
                    efforts.append(total_data["effort"])
                if "bugs" in total_data:
                    bugs.append(total_data["bugs"])

        return HalsteadMetrics(
            self._safe_average(volumes),
            self._safe_average(difficulties),
            self._safe_average(efforts),
            self._safe_average(bugs),
        )

    def _parse_raw_metrics(self, raw_metrics: dict[str, Any]) -> int:
        """Parse raw metrics and return total lines of code."""
        raw_data: dict[str, dict[str, int]] = raw_metrics.get("raw_metrics", {})
        if not raw_data:
            return 0

        return sum(file_data.get("loc", 0) for file_data in raw_data.values())

    def parse_metrics(self, raw_metrics: dict[str, Any]) -> CodeMetrics:
        """Parse radon output and extract various metrics."""
        metrics = CodeMetrics()

        metrics.average_complexity = self._parse_complexity_metrics(raw_metrics)

        maintainability_metrics = self._parse_maintainability_metrics(raw_metrics)
        metrics.average_maintainability = maintainability_metrics.average
        metrics.min_maintainability = maintainability_metrics.minimum

        halstead_metrics = self._parse_halstead_metrics(raw_metrics)
        metrics.average_halstead_volume = halstead_metrics.volume
        metrics.average_halstead_difficulty = halstead_metrics.difficulty
        metrics.average_halstead_effort = halstead_metrics.effort
        metrics.average_halstead_bugs = halstead_metrics.bugs

        metrics.total_loc = self._parse_raw_metrics(raw_metrics)

        return metrics


def format_change(old: float, new: float, *, higher_is_better: bool = False) -> str:
    """Format change with appropriate emoji."""
    if old == 0 and new == 0:
        return "No change!"

    if old == 0:
        return f"New: {new:.2f}."

    diff = new - old
    percent_change = diff / old * 100

    if abs(percent_change) < MIN_PERCENT_CHANGE_THRESHOLD:
        return f"{new:.2f} (no significant change)."

    emoji = "✅" if (diff > 0) == higher_is_better else "⚠️"
    sign = "+" if diff > 0 else ""
    return f"{emoji} {sign}{diff:.2f} ({percent_change:+.1f}%)."


class MetricsAnalyzer:
    """Analyzes, compares, and reports on code metrics between two branches."""

    def __init__(self, target: CodeMetrics, pr: CodeMetrics) -> None:
        self.target = target
        self.pr = pr

    def _complexity_analysis(self) -> ComplexityAnalysisData:
        """Generate complexity analysis as a dictionary."""
        warnings: list[str] = []

        if self.pr.average_complexity > HIGH_COMPLEXITY_THRESHOLD:
            warnings.append("⚠️ High complexity detected - consider refactoring!")
        elif self.pr.average_complexity > MODERATE_COMPLEXITY_THRESHOLD:
            warnings.append("📊 Moderate complexity - monitor for increases.")

        data: ComplexityAnalysisData = {
            "target": self.target.average_complexity,
            "pr": self.pr.average_complexity,
            "change": format_change(self.target.average_complexity, self.pr.average_complexity),
            "warnings": warnings,
        }

        return data

    def _maintainability_analysis(self) -> MaintainabilityAnalysisData:
        """Generate maintainability analysis as a dictionary."""
        warnings: list[str] = []

        if self.pr.min_maintainability < LOW_MAINTAINABILITY_THRESHOLD:
            warnings.append("🚨 Low maintainability detected - needs attention!")
        elif self.pr.average_maintainability < MODERATE_MAINTAINABILITY_THRESHOLD:
            warnings.append("📈 Moderate maintainability - room for improvement.")

        data: MaintainabilityAnalysisData = {
            "target_average": self.target.average_maintainability,
            "pr_average": self.pr.average_maintainability,
            "change": format_change(
                self.target.average_maintainability,
                self.pr.average_maintainability,
                higher_is_better=True,
            ),
            "min_mi": self.pr.min_maintainability,
            "warnings": warnings,
        }

        return data

    def _halstead_analysis(self) -> HalsteadAnalysisData:
        """Generate Halstead metrics analysis as a dictionary."""
        warnings: list[str] = []

        if self.pr.average_halstead_difficulty > HIGH_DIFFICULTY_THRESHOLD:
            warnings.append("🧠 High difficulty detected - code may be hard to understand!")

        data: HalsteadAnalysisData = {
            "volume": format_change(
                self.target.average_halstead_volume, self.pr.average_halstead_volume
            ),
            "difficulty": format_change(
                self.target.average_halstead_difficulty, self.pr.average_halstead_difficulty
            ),
            "effort": format_change(
                self.target.average_halstead_effort, self.pr.average_halstead_effort
            ),
            "delivered_bugs": format_change(
                self.target.average_halstead_bugs, self.pr.average_halstead_bugs
            ),
            "warnings": warnings,
        }

        return data

    def _loc_analysis(self) -> LOCAnalysisData:
        """Generate lines of code analysis as a dictionary."""
        warnings: list[str] = []

        if self.pr.total_loc > self.target.total_loc * SIGNIFICANT_LOC_INCREASE_FACTOR:
            warnings.append("📏 Significant code length increase - ensure adequate testing!")

        data: LOCAnalysisData = {
            "target": self.target.total_loc,
            "pr": self.pr.total_loc,
            "change": format_change(float(self.target.total_loc), float(self.pr.total_loc)),
            "warnings": warnings,
        }

        return data

    def generate_report_data(self) -> CompleteReportData:
        """Generate the complete comparison report as a dictionary."""
        return {
            "cyclomatic_complexity": self._complexity_analysis(),
            "maintainability_index": self._maintainability_analysis(),
            "lines_of_code": self._loc_analysis(),
            "halstead_metrics": self._halstead_analysis(),
            "metadata": {"analysis_disclaimer": "This analysis is for guidance only"},
        }


class SummaryMetricsFormatter:
    """Formats and prints summary metrics."""

    def __init__(self, report_data: CompleteReportData) -> None:
        self.report_data = report_data

    def _create_complexity_panel(self, complexity_data: ComplexityAnalysisData) -> Panel:
        """Create a panel for cyclomatic complexity analysis."""
        complexity_table = Table(title="Cyclomatic Complexity Analysis")
        complexity_table.add_column("Metric", style="cyan")
        complexity_table.add_column("Value", style="magenta")

        complexity_table.add_row("Target", f"{complexity_data['target']:.2f}")
        complexity_table.add_row("PR", f"{complexity_data['pr']:.2f}")
        complexity_table.add_row("Change", complexity_data["change"])

        complexity_content = [complexity_table, *complexity_data["warnings"]]

        return Panel(Group(*complexity_content), title="[bold]Cyclomatic Complexity[/bold]")

    def _create_maintainability_panel(
        self, maintainability_data: MaintainabilityAnalysisData
    ) -> Panel:
        """Create a panel for maintainability index analysis."""
        maintainability_table = Table(title="Maintainability Index Analysis")
        maintainability_table.add_column("Metric", style="cyan")
        maintainability_table.add_column("Value", style="magenta")

        maintainability_table.add_row(
            "Target Average", f"{maintainability_data['target_average']:.2f}"
        )
        maintainability_table.add_row("PR Average", f"{maintainability_data['pr_average']:.2f}")
        maintainability_table.add_row("Change", maintainability_data["change"])
        maintainability_table.add_row("Min MI", f"{maintainability_data['min_mi']:.2f}")

        maintainability_content = [maintainability_table, *maintainability_data["warnings"]]

        return Panel(Group(*maintainability_content), title="[bold]Maintainability Index[/bold]")

    def _create_halstead_panel(self, halstead_data: HalsteadAnalysisData) -> Panel:
        """Create a panel for Halstead metrics analysis."""
        halstead_table = Table(title="Halstead Metrics Analysis")
        halstead_table.add_column("Metric", style="cyan")
        halstead_table.add_column("Change", style="magenta")

        halstead_table.add_row("Volume", halstead_data["volume"])
        halstead_table.add_row("Difficulty", halstead_data["difficulty"])
        halstead_table.add_row("Effort", halstead_data["effort"])
        halstead_table.add_row("Delivered Bugs", halstead_data["delivered_bugs"])

        halstead_content = [halstead_table, *halstead_data["warnings"]]

        return Panel(Group(*halstead_content), title="[bold]Halstead Metrics[/bold]")

    def _create_loc_panel(self, loc_data: LOCAnalysisData) -> Panel:
        """Create a panel for lines of code analysis."""
        loc_table = Table(title="Lines of Code Analysis")
        loc_table.add_column("Metric", style="cyan")
        loc_table.add_column("Value", style="magenta")

        loc_table.add_row("Target", str(loc_data["target"]))
        loc_table.add_row("PR", str(loc_data["pr"]))
        loc_table.add_row("Change", loc_data["change"])

        loc_content = [loc_table, *loc_data["warnings"]]

        return Panel(Group(*loc_content), title="[bold]Lines of Code[/bold]")

    def to_rich(self) -> RenderableType:
        """Generate and print the complete comparison report using rich tables."""
        panels = [
            self._create_complexity_panel(self.report_data["cyclomatic_complexity"]),
            self._create_maintainability_panel(self.report_data["maintainability_index"]),
            self._create_loc_panel(self.report_data["lines_of_code"]),
            self._create_halstead_panel(self.report_data["halstead_metrics"]),
        ]

        return Panel(
            Group(*panels),
            title="[bold blue]Code Metrics Panels[/bold blue]",
            subtitle=f"[italic]{self.report_data['metadata']['analysis_disclaimer']}[/italic]",
        )

    def to_json(self) -> str:
        """Print report data as JSON."""
        return json.dumps(self.report_data)


class DetailedMetricsFormatter:
    """Formats and prints detailed metrics data in various output formats."""

    def __init__(self, target_detailed: dict[str, Any], pr_detailed: dict[str, Any]) -> None:
        self.target_detailed = target_detailed
        self.pr_detailed = pr_detailed

    def to_rich(self) -> RenderableType:
        """Print detailed metrics data using rich formatting for Action logs."""
        return Panel(
            Group(
                Panel(
                    JSON(json.dumps(self.target_detailed), indent=2),
                    title="Target Branch Detailed Metrics",
                ),
                Panel(
                    JSON(json.dumps(self.pr_detailed), indent=2),
                    title="PR Branch Detailed Metrics",
                ),
            ),
            title="Detailed metrics from radon",
        )

    def to_json(self) -> str:
        """Print detailed metrics data as JSON."""
        output = {
            "target_branch_detailed_metrics": self.target_detailed,
            "pr_branch_detailed_metrics": self.pr_detailed,
        }
        return json.dumps(output)


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Compare code metrics between two Git branches using radon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "target_branch", help="Target branch to compare against (e.g., 'main', 'origin/main')"
    )

    parser.add_argument(
        "pr_branch", help="PR/feature branch to analyze (e.g., 'feature-branch', 'HEAD')"
    )

    verbosity_group = parser.add_argument_group("Verbosity Options")
    verbosity_exclusion = verbosity_group.add_mutually_exclusive_group()
    verbosity_exclusion.add_argument(
        "--summary",
        action="store_true",
        default=True,
        help="Show summarized metrics comparison (default)",
    )
    verbosity_exclusion.add_argument(
        "--detail", action="store_true", help="Show detailed metrics data directly from radon"
    )

    parser.add_argument(
        "--format",
        type=OutputFormat,
        choices=list(OutputFormat),
        default=OutputFormat.RICH,
        help="Output format: 'rich' for styled tables/panels (default), 'raw' for JSON output",
    )

    return parser.parse_args()


def _git_switch(branch: str) -> None:
    """Switch to the specified Git branch."""
    subprocess.run(["/usr/bin/git", "switch", branch], check=True)


def main() -> None:
    """Compare radon metrics between target and PR branches."""
    args = parse_arguments()
    metrics_collector = RadonMetricsCollector()

    console = Console()

    console.print(f"Analyzing metrics for PR's target branch: [bold]{args.target_branch}[/bold].")
    _git_switch(args.target_branch)
    target_raw = metrics_collector.collect_metrics()
    target_metrics = metrics_collector.parse_metrics(target_raw)

    console.print(f"Analyzing metrics for PR's branch: [bold]{args.pr_branch}[/bold].")
    _git_switch(args.pr_branch)
    pr_raw = metrics_collector.collect_metrics()
    pr_metrics = metrics_collector.parse_metrics(pr_raw)

    if args.detail:
        detailed_formatter = DetailedMetricsFormatter(target_raw, pr_raw)
        if args.format == OutputFormat.RAW:
            printable_result = detailed_formatter.to_json()
        else:
            printable_result = detailed_formatter.to_rich()
    else:
        analyzer = MetricsAnalyzer(target_metrics, pr_metrics)
        report_data = analyzer.generate_report_data()

        summary_formatter = SummaryMetricsFormatter(report_data)
        if args.format == OutputFormat.RAW:
            printable_result = summary_formatter.to_json()
        else:
            printable_result = summary_formatter.to_rich()

    console = Console()
    console.print(printable_result)


if __name__ == "__main__":
    main()

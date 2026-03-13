# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pygithub>=2.0.0",
#     "rich",
#     "pydantic"
# ]
# ///
"""Calculate various metrics used in the delivery report.

Run with `uv run scripts/github_metrics.py --help`.
"""

from __future__ import annotations

import argparse
import logging
import os
import warnings
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from functools import cache
from itertools import chain, pairwise
from statistics import StatisticsError, mean, median, quantiles
from typing import TYPE_CHECKING, ClassVar, Self

from github import Auth, Github
from pydantic import BaseModel
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from github.Commit import Commit
    from github.GitRelease import GitRelease
    from github.Issue import Issue
    from github.IssueComment import IssueComment
    from github.PullRequest import PullRequest
    from github.PullRequestReview import PullRequestReview
    from github.Repository import Repository
    from github.WorkflowRun import WorkflowRun

logger = logging.getLogger(__name__)

NOW = datetime.now(UTC)
CONSOLE = Console()

ONE_DAY_HOURS = 24
KILO_LIMIT = 1000


class Verbosity(IntEnum):
    """Verbosity levels for output detail."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3


def format_hours(hours: float | None) -> Text:
    """Return a Text that has a specific style for different amount of hours.

    Args:
        hours (float | None): The hours to format.

    Returns:
        Text: A styled rich `Text`.
            - Dim style for `None` values.
            - Green for hours ∈ [0, 24].
            - Yellow for hours ∈ (24, 48).
            - Red for hours ∈ [48, +inf).
    """
    if hours is None:
        return Text("null", style="dim")

    formatted = f"{hours:.2f}"

    if hours <= ONE_DAY_HOURS:
        style = "green"
    elif hours < 2 * ONE_DAY_HOURS:
        style = "yellow"
    else:
        style = "red"
    return Text(formatted, style=style)


def format_number(num: int) -> str:
    """Format large numbers with 'k' suffix for thousands."""
    if num >= KILO_LIMIT:
        return f"{num / 1000:.1f}k"
    return str(num)


class AggregateStatistics(BaseModel):
    """Aggregate statistics for a metric (collection of observations).

    Attributes:
        min (float | None): Minimum value in the observations, or None if no observations.
        percentile_25 (float | None): 25th percentile value (first quartile), or None if
            less than 3 observations.
        median (float | None): Median value (50th percentile), or None if no observations.
        mean (float | None): Mean value of the observations, or None if no observations.
        percentile_75 (float | None): 75th percentile value (third quartile), or None if
            less than 3 observations.
        max (float | None): Maximum value in the observations, or None if no observations.
        observation_count (int): Number of observations used in the calculation.
    """

    min: float | None
    percentile_25: float | None
    median: float | None
    mean: float | None
    percentile_75: float | None
    max: float | None
    observation_count: int

    @staticmethod
    def format_float(value: float | None) -> Text:
        """Format a float value as a rich `Text`."""
        if value is None:
            return Text("null", style="dim")
        if value < 0:
            return Text("-", style="dim")
        return Text(f"{value:.2f}")

    def format_observation_count(self) -> Text:
        """Format the observation count as a rich `Text` object with color styling.

        Returns:
            Text: Colored text depending on the count.
                - Dim style for count of 0.
                - Red for counts <= 3 (insufficient data).
                - Yellow for counts <= 10 (limited data).
                - Green for counts > 10 (sufficient data).
        """
        if self.observation_count == 0:
            return Text("0", style="dim")

        if self.observation_count <= 3:  # noqa: PLR2004 this is indeed an arbitrary value.
            color = "red"
        elif self.observation_count <= 10:  # noqa: PLR2004 this is indeed an arbitrary value.
            color = "yellow"
        else:
            color = "green"

        return Text(str(self.observation_count), style=color)

    def printable_row(self, verbosity: int = 2) -> list[Text]:
        """Return a list of statistics for display.

        Args:
            verbosity: Verbosity level for output detail.
                - If < 2: Return only mean and count.
                - If >= 2: Return all statistics (min, percentiles, median, mean, max, count).
        """
        if verbosity >= Verbosity.HIGH:
            return [
                AggregateStatistics.format_float(self.min),
                AggregateStatistics.format_float(self.percentile_25),
                AggregateStatistics.format_float(self.median),
                AggregateStatistics.format_float(self.mean),
                AggregateStatistics.format_float(self.percentile_75),
                AggregateStatistics.format_float(self.max),
                self.format_observation_count(),
            ]
        return [
            AggregateStatistics.format_float(self.mean),
            self.format_observation_count(),
        ]

    @classmethod
    def from_observations(cls, observations: Iterable[float]) -> Self:
        """Create an AggregateStatistics instance from a list of observations.

        Args:
            observations: Observations to aggregate.

        Returns:
            Self: An `AggregateStatistics` instance with calculated statistics. Edge cases:
                - If no observations are provided, all statistics will be None and count will be 0.
                - If too few observations are provided and `quantiles` fail, percentiles will be
                    None. Python <3.13 mandates at least 2 observations while >=3.13 is okay with 1.
        """
        observations = list(observations)
        if not observations:
            return cls(
                min=None,
                percentile_25=None,
                median=None,
                mean=None,
                percentile_75=None,
                max=None,
                observation_count=0,
            )

        try:
            p25, med, p75 = quantiles(observations, n=4)
        except StatisticsError:
            # Python <3.13 quantiles explodes for <= 2 observations.
            med = median(observations)
            p25 = p75 = None

        return cls(
            min=min(observations),
            percentile_25=p25,
            median=med,
            mean=mean(observations),
            percentile_75=p75,
            max=max(observations),
            observation_count=len(observations),
        )


@cache
def _get_pr_reviews_and_comments(
    pr: PullRequest,
) -> tuple[list[PullRequestReview], list[IssueComment]]:
    """Get non-bot reviews and comments for a PR.

    Args:
        pr (PullRequest): The pull request to analyze.

    Returns:
        tuple[list[PullRequestReview], list[IssueComment]]: A tuple containing non-bot and non
            pending or dismissed reviews, and non-bot comments.
    """
    reviews = [
        review
        for review in pr.get_reviews()
        if review.user.type.casefold() != "bot"
        and review.state.casefold() not in ("pending", "dismissed")
    ]
    comments = [
        comment for comment in pr.get_issue_comments() if comment.user.type.casefold() != "bot"
    ]

    return reviews, comments


def pr_statistics_table(
    title: str, caption: str | None, prs: Iterable[PullRequest], verbosity: int = 0
) -> Table:
    """Create a table showing detailed statistics for a set of PRs.

    Note: Reviews done by bots, as well as pending/dismissed reviews, are ignored.

    Args:
        title (str): The title of the table.
        caption (str | None): The caption for the table. If None, no caption is included.
        prs (Iterable[PullRequest]): The pull requests to calculate and display statistics for.
        verbosity (int): Verbosity level for output detail.
            - If < 2: Include only PR number, # commits, and time to first review/comment.
            - If >= 2: Also include additions, deletions, # changed files, and total comments.

    Returns:
        Table: PR statistics.
    """
    stats_table = Table(title=title, caption=caption)
    stats_table.add_column("PR #", style="bold")
    stats_table.add_column("# commits", style="bold")

    if verbosity >= Verbosity.HIGH:
        stats_table.add_column("Additions", style="bold")
        stats_table.add_column("Deletions", style="bold")
        stats_table.add_column("# Changed Files", style="bold")
        stats_table.add_column("Total Comments", style="bold")

    stats_table.add_column("Time to first review (h)", style="bold")
    stats_table.add_column("Time to first comment (h)", style="bold")

    for pr in prs:
        reviews, comments = _get_pr_reviews_and_comments(pr)

        first_review_time = min((review.submitted_at for review in reviews), default=None)
        hours_to_first_review = (
            (first_review_time - pr.created_at) / timedelta(hours=1) if first_review_time else None
        )

        first_comment_time = min((comment.created_at for comment in comments), default=None)
        hours_to_first_comment = (
            (first_comment_time - pr.created_at) / timedelta(hours=1)
            if first_comment_time
            else None
        )

        if verbosity >= Verbosity.HIGH:
            stats_table.add_row(
                f"#{pr.number}",
                format_number(pr.commits),
                Text(f"+{format_number(pr.additions)}", style="green"),
                Text(f"-{format_number(pr.deletions)}", style="red"),
                format_number(pr.changed_files),
                format_number(pr.review_comments + pr.comments),
                format_hours(hours_to_first_review),
                format_hours(hours_to_first_comment),
            )
        else:
            stats_table.add_row(
                f"#{pr.number}",
                format_number(pr.commits),
                format_hours(hours_to_first_review),
                format_hours(hours_to_first_comment),
            )
    return stats_table


class PullRequestStats:
    """PR related statistics.

    Args:
        merged_in_period (Iterable[PullRequest]): PRs merged within the analysis period.
        opened_in_period (Iterable[PullRequest]): PRs opened within the analysis period.
        currently_open (Iterable[PullRequest]): PRs currently open.
        start_date (datetime): The start date of the analysis period.
        verbosity (int): Verbosity level for output detail.
            - 0: Show only mean and count metrics in summary tables.
            - 1: Show summary tables but omit detailed PR statistics tables.
            - 2+: Show all available details including min, percentiles, and max values.
    """

    def __init__(
        self,
        merged_in_period: Iterable[PullRequest],
        opened_in_period: Iterable[PullRequest],
        currently_open: Iterable[PullRequest],
        start_date: datetime,
        verbosity: int = 0,
    ) -> None:
        self.merged_in_period = sorted(merged_in_period, key=lambda pr: pr.number)
        self.opened_in_period = sorted(opened_in_period, key=lambda pr: pr.number)
        self.currently_open = sorted(currently_open, key=lambda pr: pr.number)
        self.start_date = start_date
        self.verbosity = verbosity

    @property
    def merged_ages(self) -> list[timedelta]:
        """Return list of PR ages at merge time.

        Returns:
            A list of timedelta objects representing the age of each PR
            when it was merged.
        """
        return [
            (pr.merged_at - pr.created_at)
            for pr in self.merged_in_period
            if pr.merged_at is not None
        ]

    @property
    def currently_opened_all_ages(self) -> list[timedelta]:
        """Return list of PR ages (as of now) for currently open PRs.

        Returns:
            A list of timedelta objects representing the current age of all
            currently open PRs.
        """
        return [(NOW - pr.created_at) for pr in self.currently_open]

    @property
    def currently_opened_ages(self) -> list[timedelta]:
        """Return list of PR ages (as of now) for currently open non-draft PRs.

        Returns:
            A list of timedelta objects representing the current age of
            currently open non-draft PRs.
        """
        return [(NOW - pr.created_at) for pr in self.currently_open if not pr.draft]

    @property
    def currently_opened_draft_ages(self) -> list[timedelta]:
        """Return list of PR ages (as of now) for currently open draft PRs."""
        return [(NOW - pr.created_at) for pr in self.currently_open if pr.draft]

    @property
    def current_amount_draft(self) -> int:
        """Return the number of currently opened draft pull requests."""
        return len([pr for pr in self.currently_open if pr.draft])

    def _period_pr_ages_display(self) -> RenderableType:
        """Create a display for PR ages during the analysis period.

        Returns:
            A RenderableType object containing tables and statistics for PRs
            in the analysis period.
        """
        summary_table = Table(
            title="Aggregate PR Ages",
            caption=f"Calculation interval: [{self.start_date}, {NOW}].",
        )

        summary_table.add_column("Metric", style="bold")

        if self.verbosity >= Verbosity.HIGH:
            summary_table.add_column("min (days)", style="bold", justify="right")
            summary_table.add_column("Percentile 25 (days)", style="bold", justify="right")
            summary_table.add_column("median (days)", style="bold", justify="right")

        summary_table.add_column("mean (days)", style="bold", justify="right")

        if self.verbosity >= Verbosity.HIGH:
            summary_table.add_column("Percentile 75 (days)", style="bold", justify="right")
            summary_table.add_column("max (days)", style="bold", justify="right")

        summary_table.add_column("Count", style="bold", justify="right")

        merged_stats = AggregateStatistics.from_observations(
            duration / timedelta(days=1) for duration in self.merged_ages
        )
        open_stats = AggregateStatistics.from_observations(
            duration / timedelta(days=1) for duration in self.currently_opened_all_ages
        )

        summary_table.add_row(
            "Merged in period", *merged_stats.printable_row(verbosity=self.verbosity)
        )
        summary_table.add_row(
            "Opened in period", *open_stats.printable_row(verbosity=self.verbosity)
        )

        if self.verbosity >= 1:
            stats_table = pr_statistics_table(
                title="PR list",
                caption=f"Calculation interval: [{self.start_date}, {NOW}].",
                prs=chain(self.merged_in_period, self.opened_in_period),
                verbosity=self.verbosity,
            )
            return Group(summary_table, stats_table)
        return summary_table

    def _current_pr_display(self) -> RenderableType:
        """Create a display for currently open PRs.

        Returns:
            A RenderableType object containing tables and statistics for
            currently open PRs.
        """
        tree = Tree("PR types", style="bold")
        n_total, n_draft = len(self.currently_open), self.current_amount_draft
        tree.add(Text(f"Total: {n_total}"))
        tree.add(Text(f"Draft: {n_draft}", style="yellow"))
        tree.add(Text(f"Non-draft: {n_total - n_draft}", style="green"))

        summary_table = Table(title="Aggregate PR Ages")

        summary_table.add_column("Metric", style="bold")

        if self.verbosity >= Verbosity.HIGH:
            summary_table.add_column("min (days)", style="bold", justify="right")
            summary_table.add_column("Percentile 25 (days)", style="bold", justify="right")
            summary_table.add_column("median (days)", style="bold", justify="right")

        summary_table.add_column("mean (days)", style="bold", justify="right")

        if self.verbosity >= Verbosity.HIGH:
            summary_table.add_column("Percentile 75 (days)", style="bold", justify="right")
            summary_table.add_column("max (days)", style="bold", justify="right")

        summary_table.add_column("Count", style="bold", justify="right")

        summary_table.add_row(
            "All",
            *AggregateStatistics.from_observations(
                duration / timedelta(days=1) for duration in self.currently_opened_all_ages
            ).printable_row(verbosity=self.verbosity),
        )
        summary_table.add_row(
            "Non-draft",
            *AggregateStatistics.from_observations(
                duration / timedelta(days=1) for duration in self.currently_opened_ages
            ).printable_row(verbosity=self.verbosity),
        )
        summary_table.add_row(
            "Draft",
            *AggregateStatistics.from_observations(
                duration / timedelta(days=1) for duration in self.currently_opened_draft_ages
            ).printable_row(verbosity=self.verbosity),
        )

        if self.verbosity >= 1:
            stats_table = pr_statistics_table(
                title="PR list", caption=None, prs=self.currently_open, verbosity=self.verbosity
            )
            return Group(tree, summary_table, stats_table)
        return Group(tree, summary_table)

    def to_rich(self) -> RenderableType:
        """Convert `self` to a pretty Rich renderable."""
        period = Panel(self._period_pr_ages_display(), title="Period PR Statistics")
        current = Panel(self._current_pr_display(), title="Currently open PR Statistics")

        return Group(period, current)


class ReleaseStats:
    """Stores all calculated statistics for releases.

    Args:
        releases_with_commits (Mapping[GitRelease, list[Commit]]): Mapping of releases to
            their commits.
        start_date (datetime): The start date of the analysis period.
        verbosity (int): Verbosity level for output detail.
            - 0: Show only mean and count metrics in summary tables.
            - 1: Show summary data but omit some detailed metrics.
            - 2+: Show all available details including min, percentiles, and max values.
    """

    def __init__(
        self,
        releases_with_commits: Mapping[GitRelease, list[Commit]],
        start_date: datetime,
        verbosity: int = 0,
    ) -> None:
        self.start_date = start_date
        self.verbosity = verbosity

        ordered_releases = sorted(releases_with_commits.keys(), key=lambda r: r.published_at)
        self.releases = {release: releases_with_commits[release] for release in ordered_releases}

    @property
    def time_between_releases(self) -> list[timedelta]:
        """Time between consecutive releases."""
        return [(new.published_at - old.published_at) for old, new in pairwise(self.releases)]

    @property
    def commit_ages(self) -> dict[GitRelease, list[timedelta]]:
        """Ages of commits (from commit moment to release moment) for each release."""
        # GitHub is author of merge commits.
        # TODO(@sebastian-correa): What happens for squash commits?
        return {
            release: [
                release.published_at - commit.commit.author.date
                for commit in commits
                if commit.commit.committer.name.lower() != "github"
            ]
            for release, commits in self.releases.items()
        }

    def to_rich(self) -> RenderableType:
        """Convert `self` to a pretty Rich renderable."""
        release_count = Text(f"{len(self.releases)} releases in period.", style="bold green")

        tree = Tree("Days between releases", style="bold")
        time_between_stats = AggregateStatistics.from_observations(
            time_between / timedelta(days=1) for time_between in self.time_between_releases
        )

        if self.verbosity >= Verbosity.HIGH:
            tree.add(Text("min: ", style="bold") + Text(str(time_between_stats.min)))
            tree.add(
                Text("Percentile 25: ", style="bold") + Text(str(time_between_stats.percentile_25))
            )
            tree.add(Text("median: ", style="bold") + Text(str(time_between_stats.median)))

        tree.add(Text("mean: ", style="bold") + Text(str(time_between_stats.mean)))

        if self.verbosity >= Verbosity.HIGH:
            tree.add(
                Text("Percentile 75: ", style="bold") + Text(str(time_between_stats.percentile_75))
            )
            tree.add(Text("max: ", style="bold") + Text(str(time_between_stats.max)))

        summary_table = Table(
            title="Commit lead times", caption=f"Calculation interval: [{self.start_date}, {NOW}]."
        )
        summary_table.add_column("Release", style="bold")
        summary_table.add_column("Released at", style="bold", justify="right")

        if self.verbosity >= Verbosity.HIGH:
            summary_table.add_column("min (days)", style="bold", justify="right")
            summary_table.add_column("Percentile 25 (days)", style="bold", justify="right")
            summary_table.add_column("median (days)", style="bold", justify="right")

        summary_table.add_column("mean (days)", style="bold", justify="right")

        if self.verbosity >= Verbosity.HIGH:
            summary_table.add_column("Percentile 75 (days)", style="bold", justify="right")
            summary_table.add_column("max (days)", style="bold", justify="right")

        summary_table.add_column("# commits in release", style="bold", justify="right")

        for release, commit_ages in self.commit_ages.items():
            commit_ages_stats = AggregateStatistics.from_observations(
                age / timedelta(days=1) for age in commit_ages
            )

            row_data: list[RenderableType] = [
                release.tag_name,
                release.created_at.astimezone(None).isoformat(),
            ]

            if self.verbosity >= Verbosity.HIGH:
                row_data.extend(
                    [
                        commit_ages_stats.format_float(commit_ages_stats.min),
                        commit_ages_stats.format_float(commit_ages_stats.percentile_25),
                        commit_ages_stats.format_float(commit_ages_stats.median),
                    ]
                )

            row_data.append(commit_ages_stats.format_float(commit_ages_stats.mean))

            if self.verbosity >= Verbosity.HIGH:
                row_data.extend(
                    [
                        commit_ages_stats.format_float(commit_ages_stats.percentile_75),
                        commit_ages_stats.format_float(commit_ages_stats.max),
                    ]
                )

            row_data.append(commit_ages_stats.format_observation_count())

            summary_table.add_row(*row_data)

        group = Group(tree, release_count, summary_table)
        return Panel(group, title="Release Statistics")


class WorkflowStats:
    """Stores all calculated statistics for workflows.

    Args:
        main_runs (Iterable[WorkflowRun]): Main workflow runs to analyze.
        release_runs (Iterable[WorkflowRun]): Release workflow runs to analyze.
        start_date (datetime): The start date of the analysis period.
        verbosity (int): Verbosity level for output detail.
            - 0: Show only mean and count metrics in summary tables.
            - 1: Show summary data but omit some detailed metrics.
            - 2+: Show all available details including min, percentiles, and max values.
    """

    CONCLUSION_STYLES: ClassVar[dict[str, str]] = {
        "success": "green",
        "failure": "bold red",
        "neutral": "yellow",
        "cancelled": "blue",
        "skipped": "dim",
        "action_required": "orange",
        "stale": "dim",
        "timed_out": "dim",
    }

    def __init__(
        self,
        main_runs: Iterable[WorkflowRun],
        release_runs: Iterable[WorkflowRun],
        start_date: datetime,
        verbosity: int = 0,
    ) -> None:
        self.start_date = start_date
        self.verbosity = verbosity

        # Organize runs by workflow type, then by workflow ID, then by conclusion
        self.main_runs_by_id = self._organize_runs_by_id(main_runs)
        self.release_runs_by_id = self._organize_runs_by_id(release_runs)

        self.release_workflow_names = self._extract_workflow_names(release_runs)
        self.main_workflow_names = self._extract_workflow_names(main_runs)

    def _organize_runs_by_id(
        self, runs: Iterable[WorkflowRun]
    ) -> defaultdict[int, defaultdict[str, list[WorkflowRun]]]:
        """Organize runs by workflow ID and conclusion."""
        organized_runs: defaultdict[int, defaultdict[str, list[WorkflowRun]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for run in runs:
            # Use 'pending' if conclusion is None
            conclusion = run.conclusion or "pending"
            organized_runs[run.workflow_id][conclusion].append(run)
        return organized_runs

    def _extract_workflow_names(self, runs: Iterable[WorkflowRun]) -> dict[int, str]:
        """Extract workflow names from runs."""
        return {run.workflow_id: run.name for run in runs}

    def _calculate_run_durations(
        self, runs_by_id: defaultdict[int, defaultdict[str, list[WorkflowRun]]]
    ) -> defaultdict[int, defaultdict[str, list[timedelta]]]:
        """Calculate run durations by workflow ID and conclusion."""
        durations: defaultdict[int, defaultdict[str, list[timedelta]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for workflow_id, runs_by_conclusion in runs_by_id.items():
            for conclusion, runs in runs_by_conclusion.items():
                for run in runs:
                    if run.updated_at and run.run_started_at:
                        durations[workflow_id][conclusion].append(
                            run.updated_at - run.run_started_at
                        )
        return durations

    def _build_workflow_tree(
        self,
        runs_by_id: defaultdict[int, defaultdict[str, list[WorkflowRun]]],
        workflow_names: dict[int, str],
        title: str,
    ) -> Tree:
        """Build a tree showing breakdown of workflow runs by ID and conclusion."""
        tree = Tree(title, style="bold")

        # Calculate totals across all workflows
        all_conclusions: defaultdict[str, int] = defaultdict(int)
        total_runs = 0

        for runs_by_conclusion in runs_by_id.values():
            workflow_total = sum(len(runs) for runs in runs_by_conclusion.values())
            total_runs += workflow_total

            for conclusion, runs in runs_by_conclusion.items():
                all_conclusions[conclusion] += len(runs)

        # Add total metrics across all workflows
        if total_runs > 0:
            total_tree = tree.add("All workflows (total)", style="bold")
            for conclusion, count in all_conclusions.items():
                header = Text(
                    f"{conclusion}: ", style=self.CONCLUSION_STYLES.get(conclusion.lower(), "")
                )
                value = Text(f"{count} ({count / total_runs:.2%})")
                total_tree.add(header + value)

        # Add breakdown by workflow
        for workflow_id, runs_by_conclusion in runs_by_id.items():
            workflow_total = sum(len(runs) for runs in runs_by_conclusion.values())
            if workflow_total == 0:
                continue

            workflow_name = workflow_names.get(workflow_id, f"Unknown Workflow {workflow_id}")
            subtree = tree.add(
                f"{workflow_name} (id={workflow_id}) (total={workflow_total})", style="bold"
            )

            for conclusion, runs in runs_by_conclusion.items():
                if len(runs) == 0:
                    continue
                header = Text(
                    f"{conclusion}: ", style=self.CONCLUSION_STYLES.get(conclusion.lower(), "")
                )
                value = Text(f"{len(runs)} ({len(runs) / workflow_total:.2%})")
                subtree.add(header + value)

        return tree

    def _create_duration_stats_table(
        self,
        title: str,
        caption: str | None = None,
        *,
        include_workflow_column: bool = False,
    ) -> Table:
        """Create a table with appropriate columns for duration statistics.

        Args:
            title: The title of the table
            caption: Optional caption for the table
            include_workflow_column: Whether to include a workflow column (for summary tables)

        Returns:
            Table: A table with appropriate columns for duration statistics
        """
        table = Table(title=title, caption=caption)

        if include_workflow_column:
            table.add_column("Workflow", style="bold")

        table.add_column("Status", style="bold")

        if self.verbosity >= Verbosity.HIGH:
            table.add_column("min (min)", style="bold", justify="right")
            table.add_column("Percentile 25 (min)", style="bold", justify="right")
            table.add_column("median (min)", style="bold", justify="right")

        table.add_column("mean (min)", style="bold", justify="right")

        if self.verbosity >= Verbosity.HIGH:
            table.add_column("Percentile 75 (min)", style="bold", justify="right")
            table.add_column("max (min)", style="bold", justify="right")

        table.add_column("Run count", style="bold", justify="right")

        return table

    def _add_duration_stats_row(
        self,
        table: Table,
        durations: list[timedelta],
        status_text: Text | str,
        workflow_name: RenderableType | None = None,
        style: str | None = None,
    ) -> None:
        """Add a row with duration statistics to a table.

        Args:
            table: The table to add the row to
            durations: List of durations to calculate statistics from
            status_text: The status text to display (or a Text object for styled text)
            workflow_name: Optional workflow name (for summary tables)
            style: Optional style for the entire row
        """
        if not durations:
            return

        stats = AggregateStatistics.from_observations(
            duration / timedelta(minutes=1) for duration in durations
        )

        # Convert string status to styled Text if needed
        if isinstance(status_text, str):
            conclusion_style = self.CONCLUSION_STYLES.get(status_text.lower(), "")
            status_text = Text(status_text, style=conclusion_style)

        row_data: list[RenderableType] = []
        if workflow_name is not None:
            row_data.append(workflow_name)

        row_data.append(status_text)
        row_data.extend(stats.printable_row(verbosity=self.verbosity))

        table.add_row(*row_data, style=style)

    def _build_duration_table(
        self,
        runs_by_id: defaultdict[int, defaultdict[str, list[WorkflowRun]]],
        workflow_names: dict[int, str],
        title: str,
    ) -> Group:
        """Build tables showing workflow run durations by ID and conclusion.

        Creates one table per workflow with a total row for each workflow that has multiple statuses
        and then creates an overall table combining all workflows.

        Args:
            runs_by_id: Workflow runs organized by ID and conclusion
            workflow_names: Mapping of workflow IDs to names
            title: The title prefix for the overall table

        Returns:
            Group: A group of tables (one per workflow + one overall)
        """
        durations = self._calculate_run_durations(runs_by_id)
        tables: list[Table] = []
        all_durations: list[timedelta] = []

        # First, create a table for each workflow
        for workflow_id, durations_by_conclusion in durations.items():
            workflow_name = workflow_names.get(workflow_id, f"Unknown Workflow {workflow_id}")
            workflow_durations: list[timedelta] = []

            # Skip if no durations for this workflow
            if not any(duration_list for duration_list in durations_by_conclusion.values()):
                continue

            # Create a table for this workflow
            workflow_table = self._create_duration_stats_table(
                title=f"{workflow_name} Workflow Run Durations"
            )

            # Add rows for each conclusion
            for conclusion, duration_list in durations_by_conclusion.items():
                if not duration_list:
                    continue

                workflow_durations.extend(duration_list)
                all_durations.extend(duration_list)

                self._add_duration_stats_row(workflow_table, duration_list, conclusion)

            # Add a total row if there are multiple conclusions
            if len([d for d in durations_by_conclusion.values() if d]) > 1 and workflow_durations:
                self._add_duration_stats_row(
                    workflow_table, workflow_durations, Text("Total", style="bold"), style="dim"
                )

            tables.append(workflow_table)

        # Now create an overall table combining all workflows
        if all_durations:
            overall_table = self._create_duration_stats_table(
                title=f"{title} - Overall Summary",
                caption=f"Calculation interval: [{self.start_date}, {NOW}].",
                include_workflow_column=True,
            )

            # Add a row for each workflow's total durations
            for workflow_id, durations_by_conclusion in durations.items():
                workflow_name = workflow_names.get(workflow_id, f"Unknown Workflow {workflow_id}")
                workflow_durations: list[timedelta] = []

                for duration_list in durations_by_conclusion.values():
                    workflow_durations.extend(duration_list)

                if workflow_durations:
                    self._add_duration_stats_row(
                        overall_table,
                        workflow_durations,
                        Text("Total", style="bold"),
                        workflow_name,
                    )

            # Add an overall total row
            self._add_duration_stats_row(
                overall_table,
                all_durations,
                Text("Total", style="bold"),
                Text("All Workflows", style="bold"),
                style="bold",
            )

            tables.append(overall_table)

        return Group(*tables)

    def _main_runs_panel(self) -> Panel:
        """Create a panel for main workflow runs."""
        panel_title = "Main Workflow Runs"
        if not self.main_runs_by_id:
            return Panel(
                Text("No main workflow runs found in the period.", style="italic"),
                title=panel_title,
            )

        tree = self._build_workflow_tree(
            self.main_runs_by_id, self.main_workflow_names, "Main Workflow Runs Breakdown"
        )

        tables = self._build_duration_table(
            self.main_runs_by_id, self.main_workflow_names, "Main Workflow Run Durations"
        )

        return Panel(Group(tree, tables), title=panel_title)

    def _release_runs_panel(self) -> Panel:
        """Create a panel for release workflow runs."""
        if not self.release_runs_by_id:
            return Panel(
                Text("No release workflow runs found in the period.", style="italic"),
                title="Release Workflow Runs",
            )

        tree = self._build_workflow_tree(
            self.release_runs_by_id, self.release_workflow_names, "Release Workflow Runs Breakdown"
        )

        tables = self._build_duration_table(
            self.release_runs_by_id, self.release_workflow_names, "Release Workflow Run Durations"
        )

        return Panel(Group(tree, tables), title="Release Workflow Runs")

    def to_rich(self) -> RenderableType:
        """Create a rich renderable with panels for main and release workflow runs."""
        main_panel = self._main_runs_panel()
        release_panel = self._release_runs_panel()

        return Group(main_panel, release_panel)


@cache
def _issue_as_pull_request(issue: Issue) -> PullRequest:
    """Convert an Issue to a PullRequest."""
    return issue.as_pull_request()


@cache
def _get_prs_created_in_period(
    client: Github, project_name: str, start_date: datetime, end_date: datetime | None = None
) -> list[PullRequest]:
    """Get all PRs created in a given period."""
    end_date = end_date or NOW

    query = f"repo:{project_name} is:pr created:{start_date.isoformat()}..{end_date.isoformat()}"
    search_results = client.search_issues(query, sort="updated", order="desc")

    return [_issue_as_pull_request(issue_result) for issue_result in search_results]


@cache
def _get_prs_merged_in_period(
    client: Github, project_name: str, start_date: datetime, end_date: datetime | None = None
) -> list[PullRequest]:
    """Get all PRs merged in a given period."""
    end_date = end_date or NOW

    query = f"repo:{project_name} is:pr merged:{start_date.isoformat()}..{end_date.isoformat()}"
    search_results = client.search_issues(query, sort="updated", order="desc")

    return [_issue_as_pull_request(issue_result) for issue_result in search_results]


class GitHubRepoStatisticsCalculator:
    """GitHub repository statistics calculator.

    Args:
        repo_name (str): Name of the GitHub repository.
        owner (str): Owner of the repository. Defaults to "tryolabs".
        github_token (str | None): GitHub Personal Access Token. If not provided, it will read the
            `GITHUB_TOKEN` environment variable.
    """

    def __init__(
        self, repo_name: str, owner: str = "tryolabs", *, github_token: str | None = None
    ) -> None:
        token = github_token or os.environ.get("GITHUB_TOKEN")
        if not token:
            msg = (
                "GitHub token is required. Please directly pass it or set the GITHUB_TOKEN "
                "environment variable."
            )
            raise ValueError(msg)

        token = Auth.Token(token)
        self.client = Github(auth=token)

        self._owner = owner
        self._repo_name = repo_name
        self.project_name = f"{self._owner}/{self._repo_name}"

        self._repo: Repository | None = None

    @property
    def repo(self) -> Repository:
        """Cached `Repository` getter."""
        if self._repo is None:
            self._repo = self.client.get_repo(self.project_name)
        return self._repo

    def pull_request_statistics(self, start_date: datetime, verbosity: int = 0) -> PullRequestStats:
        """Get pull request statistics for the repository.

        Args:
            start_date (datetime): The start date for the analysis period.
            verbosity (int): Verbosity level for output detail.

        Returns:
            PullRequestStats: PR statistics.
        """
        merged_prs = _get_prs_merged_in_period(self.client, self.project_name, start_date)
        opened_in_period = _get_prs_created_in_period(self.client, self.project_name, start_date)
        currently_opened_prs = list(
            self.repo.get_pulls(state="open", sort="updated", direction="desc")
        )

        return PullRequestStats(
            merged_in_period=merged_prs,
            opened_in_period=opened_in_period,
            currently_open=currently_opened_prs,
            start_date=start_date,
            verbosity=verbosity,
        )

    def release_commits(
        self, start_date: datetime, all_releases: Iterable[GitRelease]
    ) -> dict[GitRelease, list[Commit]]:
        """Get all commits included in each relevant release.

        Period releases are those after the `start_date` that aren't draft or prerelease.

        Args:
            start_date (datetime): The start date for the analysis period.
            all_releases (Iterable[GitRelease]): All releases in the repository.

        Returns:
            dict[GitRelease, list[Commit]]: A mapping of releases to their commits.
        """
        relevant_releases = [
            release
            for release in all_releases
            if (release.published_at >= start_date and not release.draft and not release.prerelease)
        ]

        releases_before_window = [r for r in all_releases if r.published_at < start_date]
        last_release_before_window = max(releases_before_window, key=lambda r: r.published_at)
        compare_releases = sorted(
            [last_release_before_window, *relevant_releases], key=lambda r: r.published_at
        )

        commits: dict[GitRelease, list[Commit]] = {}
        for old, new in pairwise(compare_releases):
            if old.tag_name == new.tag_name:  # Skip if re-release.
                continue

            comparison = self.repo.compare(base=old.tag_name, head=new.tag_name)
            commits_in_release = list(comparison.commits)
            ahead_by_limit = 250
            if (
                comparison.ahead_by > len(commits_in_release)
                and comparison.ahead_by > ahead_by_limit
            ):
                # * Not sure this is true. It's hard to verify.
                warnings.warn(
                    f"Commit list for {old.tag_name}...{new.tag_name} may be truncated (ahead by "
                    f"{comparison.ahead_by} > {ahead_by_limit}) because there are too many commits "
                    f"in the release ({len(commits_in_release)}).",
                    stacklevel=2,
                )

            commits[new] = commits_in_release
        return commits

    def release_statistics(self, start_date: datetime, verbosity: int = 0) -> ReleaseStats:
        """Get release statistics for the repository.

        Args:
            start_date (datetime): The start date for the analysis period.
            verbosity (int): Verbosity level for output detail.
        """
        # TODO(@sebastian-correa): For the first release compare against the first commit.
        all_releases: list[GitRelease] = list(self.repo.get_releases())

        releases_with_commits = self.release_commits(start_date, all_releases)
        return ReleaseStats(
            releases_with_commits=releases_with_commits, start_date=start_date, verbosity=verbosity
        )

    def workflow_statistics(self, start_date: datetime, verbosity: int = 0) -> WorkflowStats:
        """Get workflow statistics for the repository.

        Args:
            start_date (datetime): The start date for the analysis period.
            verbosity (int): Verbosity level for output detail.
        """
        main_runs = self.repo.get_workflow_runs(
            branch=self.repo.get_branch("main"),
            created=f"{start_date.isoformat()}..{NOW.isoformat()}",
        )
        release_runs = self.repo.get_workflow_runs(
            event="release", created=f"{start_date.isoformat()}..{NOW.isoformat()}"
        )
        return WorkflowStats(
            main_runs=main_runs,
            release_runs=release_runs,
            start_date=start_date,
            verbosity=verbosity,
        )


def _parse_weeks(weeks: str) -> int:
    """Parse weeks argument to ensure it's a positive integer."""
    w = int(weeks)
    if w <= 0:
        msg = "Weeks must be a positive integer."
        raise ValueError(msg)
    return w


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments for GitHub metrics calculation.

    Returns:
        argparse.Namespace: Parsed command line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Compute metrics for a given GitHub project using PyGithub."
    )
    parser.add_argument(
        "--repo",
        type=str,
        required=True,
        help="GitHub repository name.",
    )
    parser.add_argument(
        "--owner",
        type=str,
        required=False,
        default="tryolabs",
        help="Owner of the repository. Defaults to 'tryolabs'.",
    )
    parser.add_argument(
        "--weeks",
        type=_parse_weeks,
        default=8,
        help="Number of weeks back to consider for metrics (default: 8).",
    )
    parser.add_argument(
        "--github-token",
        "-t",
        type=str,
        required=False,
        help=(
            "GitHub Personal Access Token for the application. If not given, tries to read the "
            "GITHUB_TOKEN environment variable."
        ),
    )
    parser.add_argument(
        "--verbosity",
        "-v",
        action="count",
        default=0,
        help="""Control the amount of detail in the output. 0 shows only mean and count metrics in
        summary tables. 1 shows summary tables but omit detailed PR statistics tables. 2+ shows all
        available details including min, percentiles, and max values. Can be used multiple times to
        increase verbosity (e.g., -vvv).""",
    )

    # Create a group for statistic flags
    stat_group = parser.add_argument_group("statistics selection")
    stat_group.add_argument(
        "--pr",
        action="store_true",
        help="Calculate pull request statistics.",
    )

    stat_group.add_argument(
        "--release",
        action="store_true",
        help="Calculate release statistics.",
    )

    stat_group.add_argument(
        "--workflow",
        action="store_true",
        help="Calculate workflow statistics.",
    )

    return parser.parse_args()


def main(
    repo: str,
    owner: str,
    weeks: int,
    github_token: str | None = None,
    *,
    calculate_pr: bool = True,
    calculate_release: bool = True,
    calculate_workflow: bool = True,
    verbosity: int = 0,
) -> None:
    """Run GitHub metrics calculation with the provided arguments.

    Args:
        repo (str): GitHub repository name.
        owner (str): Owner of the repository.
        weeks (int): Number of weeks back to consider for metrics.
        github_token (str | None): GitHub Personal Access Token for the application. See
            `GitHubRepoStatisticsCalculator`.
        calculate_pr (bool): Whether to calculate pull request statistics.
        calculate_release (bool): Whether to calculate release statistics.
        calculate_workflow (bool): Whether to calculate workflow statistics.
        verbosity (int): Verbosity level for output detail.
            - 0: Show only mean and count metrics in summary tables.
            - 1: Show summary tables but omit detailed PR statistics tables.
            - 2+: Show all available details including min, percentiles, and max values.
    """
    start_date = NOW - timedelta(weeks=weeks)

    calculator = GitHubRepoStatisticsCalculator(
        repo_name=repo, owner=owner, github_token=github_token
    )

    if calculate_pr:
        pull_request_stats = calculator.pull_request_statistics(start_date, verbosity=verbosity)
        CONSOLE.print(pull_request_stats.to_rich())

    if calculate_release:
        release_stats = calculator.release_statistics(start_date, verbosity=verbosity)
        CONSOLE.print(release_stats.to_rich())

    if calculate_workflow:
        workflow_stats = calculator.workflow_statistics(start_date, verbosity=verbosity)
        CONSOLE.print(workflow_stats.to_rich())


if __name__ == "__main__":
    args = parse_arguments()

    main(
        repo=args.repo,
        owner=args.owner,
        weeks=args.weeks,
        github_token=args.github_token,
        calculate_pr=args.pr,
        calculate_release=args.release,
        calculate_workflow=args.workflow,
        verbosity=args.verbosity,
    )

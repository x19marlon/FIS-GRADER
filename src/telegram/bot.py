"""
FIS Grader Telegram Bot.

Provides read-only access to grading and repository activity
stored in MongoDB Atlas.

Available commands:
    /start
    /help
    /whoami
    /groups
    /summary <group>
    /commits <group> [limit]
    /history <group>
    /student <email>
    /excel <group>
    /ask <question>
"""

import logging
import os
import sys
import xlsxwriter
from io import BytesIO
from pathlib import Path
from typing import Any

from pymongo import AsyncMongoClient, DESCENDING
from pymongo.server_api import ServerApi

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ``python src/telegram/bot.py`` makes ``src/telegram`` the import root.
# Add the project root so the RAG package is available with the documented
# launch command, without changing the rest of the project's layout.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# Configuration
# ============================================================

TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
MONGODB_URI_ENV = "MONGODB_URI"
ALLOWED_USERS_ENV = "TELEGRAM_ALLOWED_USER_IDS"

DATABASE_NAME = "fis_grader"

DEFAULT_COMMIT_LIMIT = 10
MAX_COMMIT_LIMIT = 25

JsonDict = dict[str, Any]


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    format=(
        "%(asctime)s - "
        "%(name)s - "
        "%(levelname)s - "
        "%(message)s"
    ),
    level=logging.INFO,
)

LOGGER = logging.getLogger(__name__)

async def generate_group_excel(
    group_id: str,
) -> tuple[BytesIO, str]:
    """
    Generate a formatted Excel report for a course group.

    The workbook contains:
        - Overview
        - Authors
        - Commits
        - History

    Args:
        group_id: Course group identifier, for example G1.

    Returns:
        A tuple containing the Excel byte stream and filename.

    Raises:
        ValueError: If the requested group does not exist.
    """

    # ========================================================
    # Load repository
    # ========================================================

    repository = await database.repositories.find_one(
        {
            "group_id": group_id
        }
    )

    if repository is None:
        raise ValueError(
            f"Group {group_id} was not found."
        )

    repository_id = repository["_id"]

    # ========================================================
    # Load latest analysis
    # ========================================================

    latest_analysis = None

    latest_cursor = (
        database.analysis_runs
        .find(
            {
                "group_id": group_id
            }
        )
        .sort(
            "executed_at",
            DESCENDING,
        )
        .limit(1)
    )

    async for analysis in latest_cursor:
        latest_analysis = analysis
        break

    # ========================================================
    # Load commits
    # ========================================================

    commits = []

    commits_cursor = (
        database.commits
        .find(
            {
                "repository_id": repository_id
            }
        )
        .sort(
            "date",
            DESCENDING,
        )
    )

    async for commit in commits_cursor:
        commits.append(commit)

    # ========================================================
    # Load historical analysis runs
    # ========================================================

    history = []

    history_cursor = (
        database.analysis_runs
        .find(
            {
                "group_id": group_id
            }
        )
        .sort(
            "executed_at",
            1,
        )
    )

    async for analysis in history_cursor:
        history.append(analysis)

    # Authors are stored as a snapshot in the latest analysis.
    authors = []

    if latest_analysis:
        authors = latest_analysis.get(
            "authors_snapshot",
            [],
        )

    # ========================================================
    # Create workbook in memory
    # ========================================================

    output = BytesIO()

    workbook = xlsxwriter.Workbook(
        output,
        {
            "in_memory": True
        },
    )

    # ========================================================
    # Workbook Formats
    # ========================================================

    title_format = workbook.add_format(
        {
            "bold": True,
            "font_size": 22,
            "font_color": "#FFFFFF",
            "bg_color": "#1F2937",
            "align": "left",
            "valign": "vcenter",
        }
    )

    subtitle_format = workbook.add_format(
        {
            "font_size": 11,
            "font_color": "#6B7280",
        }
    )

    section_format = workbook.add_format(
        {
            "bold": True,
            "font_size": 13,
            "font_color": "#FFFFFF",
            "bg_color": "#374151",
            "align": "left",
            "valign": "vcenter",
        }
    )

    kpi_label_format = workbook.add_format(
        {
            "bold": True,
            "font_color": "#6B7280",
            "align": "center",
            "valign": "vcenter",
        }
    )

    kpi_value_format = workbook.add_format(
        {
            "bold": True,
            "font_size": 20,
            "font_color": "#111827",
            "align": "center",
            "valign": "vcenter",
            "border": 1,
            "border_color": "#E5E7EB",
        }
    )

    table_header_format = workbook.add_format(
        {
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#2563EB",
            "border": 1,
            "align": "center",
            "valign": "vcenter",
        }
    )

    text_format = workbook.add_format(
        {
            "valign": "top",
        }
    )

    wrapped_format = workbook.add_format(
        {
            "text_wrap": True,
            "valign": "top",
        }
    )

    date_format = workbook.add_format(
        {
            "num_format": "yyyy-mm-dd hh:mm",
            "valign": "top",
        }
    )

    number_format = workbook.add_format(
        {
            "num_format": "#,##0",
        }
    )

    # ========================================================
    # OVERVIEW SHEET
    # ========================================================

    overview = workbook.add_worksheet(
        "Overview"
    )

    overview.hide_gridlines(2)

    overview.set_column(
        "A:A",
        24,
    )

    overview.set_column(
        "B:H",
        18,
    )

    overview.set_row(
        0,
        36,
    )

    overview.merge_range(
        "A1:H2",
        f"FIS Grader — {group_id}",
        title_format,
    )

    overview.write(
        "A3",
        repository.get(
            "full_name",
            "",
        ),
        subtitle_format,
    )

    # ========================================================
    # KPIs
    # ========================================================

    metrics = {}

    if latest_analysis:
        metrics = latest_analysis.get(
            "metrics",
            {},
        )

    overview.write(
        "A5",
        "COMMITS IN PERIOD",
        kpi_label_format,
    )

    overview.write(
        "A6",
        metrics.get(
            "period_commit_count",
            0,
        ),
        kpi_value_format,
    )

    overview.write(
        "C5",
        "HISTORICAL COMMITS",
        kpi_label_format,
    )

    overview.write(
        "C6",
        metrics.get(
            "historical_commit_count",
            0,
        ),
        kpi_value_format,
    )

    overview.write(
        "E5",
        "ACTIVE AUTHORS",
        kpi_label_format,
    )

    overview.write(
        "E6",
        metrics.get(
            "period_author_count",
            0,
        ),
        kpi_value_format,
    )

    overview.write(
        "G5",
        "STORED COMMITS",
        kpi_label_format,
    )

    overview.write(
        "G6",
        len(commits),
        kpi_value_format,
    )

    # ========================================================
    # Repository Information
    # ========================================================

    overview.merge_range(
        "A9:H9",
        "Repository Information",
        section_format,
    )

    overview.write(
        "A10",
        "Group",
        table_header_format,
    )

    overview.write(
        "B10",
        group_id,
    )

    overview.write(
        "A11",
        "Repository",
        table_header_format,
    )

    overview.write(
        "B11",
        repository.get(
            "full_name",
            "",
        ),
    )

    overview.write(
        "A12",
        "Last Analysis",
        table_header_format,
    )

    last_analysis = repository.get(
        "last_analysis_at"
    )

    if last_analysis:
        overview.write_datetime(
            "B12",
            last_analysis.replace(
                tzinfo=None
            ),
            date_format,
        )

    else:
        overview.write(
            "B12",
            "No analysis available",
        )

    # ========================================================
    # Branch Activity
    # ========================================================

    overview.merge_range(
        "A15:D15",
        "Activity by Branch",
        section_format,
    )

    overview.write(
        "A16",
        "Branch",
        table_header_format,
    )

    overview.write(
        "B16",
        "Commits",
        table_header_format,
    )

    activity_by_branch = {}

    if latest_analysis:
        activity_by_branch = (
            latest_analysis.get(
                "activity_by_branch",
                {},
            )
        )

    sorted_branches = sorted(
        activity_by_branch.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    branch_start_row = 16

    for row_index, (
        branch,
        count,
    ) in enumerate(
        sorted_branches,
        start=branch_start_row,
    ):

        overview.write(
            row_index,
            0,
            branch,
        )

        overview.write(
            row_index,
            1,
            count,
            number_format,
        )

    # ========================================================
    # Branch Chart
    # ========================================================

    if sorted_branches:

        chart = workbook.add_chart(
            {
                "type": "column"
            }
        )

        chart.add_series(
            {
                "name": "Commits",
                "categories": [
                    "Overview",
                    branch_start_row,
                    0,
                    branch_start_row
                    + len(sorted_branches)
                    - 1,
                    0,
                ],
                "values": [
                    "Overview",
                    branch_start_row,
                    1,
                    branch_start_row
                    + len(sorted_branches)
                    - 1,
                    1,
                ],
            }
        )

        chart.set_title(
            {
                "name": "Activity by Branch"
            }
        )

        chart.set_y_axis(
            {
                "name": "Commits",
                "major_gridlines": {
                    "visible": False
                },
            }
        )

        chart.set_legend(
            {
                "none": True
            }
        )

        chart.set_style(10)

        overview.insert_chart(
            "D16",
            chart,
            {
                "x_scale": 1.2,
                "y_scale": 1.1,
            },
        )

    # ========================================================
    # AUTHORS SHEET
    # ========================================================

    authors_sheet = workbook.add_worksheet(
        "Authors"
    )

    authors_sheet.hide_gridlines(2)

    authors_sheet.freeze_panes(
        1,
        0,
    )

    authors_sheet.set_column(
        "A:A",
        34,
    )

    authors_sheet.set_column(
        "B:B",
        28,
    )

    authors_sheet.set_column(
        "C:C",
        18,
    )

    authors_sheet.set_column(
        "D:D",
        45,
    )

    author_headers = [
        "Email",
        "Names Used",
        "Commits",
        "Branch Activity",
    ]

    for column, header in enumerate(
        author_headers
    ):

        authors_sheet.write(
            0,
            column,
            header,
            table_header_format,
        )

    for row, author in enumerate(
        authors,
        start=1,
    ):

        names = ", ".join(
            author.get(
                "names_used",
                [],
            )
        )

        branches = author.get(
            "branches",
            {},
        )

        branches_text = "\n".join(
            (
                f"{branch}: {count}"
                for branch, count
                in sorted(
                    branches.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            )
        )

        authors_sheet.write(
            row,
            0,
            author.get(
                "email",
                "",
            ),
            text_format,
        )

        authors_sheet.write(
            row,
            1,
            names,
            wrapped_format,
        )

        authors_sheet.write(
            row,
            2,
            author.get(
                "commit_count",
                0,
            ),
            number_format,
        )

        authors_sheet.write(
            row,
            3,
            branches_text,
            wrapped_format,
        )

    if authors:

        authors_sheet.autofilter(
            0,
            0,
            len(authors),
            len(author_headers) - 1,
        )

    # ========================================================
    # COMMITS SHEET
    # ========================================================

    commits_sheet = workbook.add_worksheet(
        "Commits"
    )

    commits_sheet.hide_gridlines(2)

    commits_sheet.freeze_panes(
        1,
        0,
    )

    commits_sheet.set_column(
        "A:A",
        20,
    )

    commits_sheet.set_column(
        "B:B",
        14,
    )

    commits_sheet.set_column(
        "C:C",
        24,
    )

    commits_sheet.set_column(
        "D:D",
        34,
    )

    commits_sheet.set_column(
        "E:E",
        55,
    )

    commits_sheet.set_column(
        "F:F",
        45,
    )

    commit_headers = [
        "Date",
        "Hash",
        "Author",
        "Email",
        "Message",
        "Branches",
    ]

    for column, header in enumerate(
        commit_headers
    ):

        commits_sheet.write(
            0,
            column,
            header,
            table_header_format,
        )

    for row, commit in enumerate(
        commits,
        start=1,
    ):

        commit_date = commit.get(
            "date"
        )

        if commit_date:

            commits_sheet.write_datetime(
                row,
                0,
                commit_date.replace(
                    tzinfo=None
                ),
                date_format,
            )

        commits_sheet.write(
            row,
            1,
            commit.get(
                "short_hash",
                "",
            ),
        )

        commits_sheet.write(
            row,
            2,
            commit.get(
                "author_name",
                "",
            ),
        )

        commits_sheet.write(
            row,
            3,
            commit.get(
                "author_email",
                "",
            ),
        )

        commits_sheet.write(
            row,
            4,
            commit.get(
                "message",
                "",
            ),
            wrapped_format,
        )

        commits_sheet.write(
            row,
            5,
            ", ".join(
                commit.get(
                    "current_remote_branches",
                    [],
                )
            ),
            wrapped_format,
        )

    if commits:

        commits_sheet.autofilter(
            0,
            0,
            len(commits),
            len(commit_headers) - 1,
        )

    # ========================================================
    # HISTORY SHEET
    # ========================================================

    history_sheet = workbook.add_worksheet(
        "History"
    )

    history_sheet.hide_gridlines(2)

    history_sheet.freeze_panes(
        1,
        0,
    )

    history_sheet.set_column(
        "A:A",
        20,
    )

    history_sheet.set_column(
        "B:E",
        22,
    )

    history_headers = [
        "Analysis Date",
        "Period Days",
        "Period Commits",
        "Historical Commits",
        "Active Authors",
    ]

    for column, header in enumerate(
        history_headers
    ):

        history_sheet.write(
            0,
            column,
            header,
            table_header_format,
        )

    for row, analysis in enumerate(
        history,
        start=1,
    ):

        executed_at = analysis.get(
            "executed_at"
        )

        period = analysis.get(
            "period",
            {},
        )

        run_metrics = analysis.get(
            "metrics",
            {},
        )

        if executed_at:

            history_sheet.write_datetime(
                row,
                0,
                executed_at.replace(
                    tzinfo=None
                ),
                date_format,
            )

        history_sheet.write(
            row,
            1,
            period.get(
                "days",
                0,
            ),
        )

        history_sheet.write(
            row,
            2,
            run_metrics.get(
                "period_commit_count",
                0,
            ),
        )

        history_sheet.write(
            row,
            3,
            run_metrics.get(
                "historical_commit_count",
                0,
            ),
        )

        history_sheet.write(
            row,
            4,
            run_metrics.get(
                "period_author_count",
                0,
            ),
        )

    # ========================================================
    # History Chart
    # ========================================================

    if history:

        history_chart = workbook.add_chart(
            {
                "type": "line"
            }
        )

        history_chart.add_series(
            {
                "name": "Commits",
                "categories": [
                    "History",
                    1,
                    0,
                    len(history),
                    0,
                ],
                "values": [
                    "History",
                    1,
                    2,
                    len(history),
                    2,
                ],
                "marker": {
                    "type": "circle"
                },
            }
        )

        history_chart.set_title(
            {
                "name": (
                    f"{group_id} Commit Activity"
                )
            }
        )

        history_chart.set_x_axis(
            {
                "name": "Analysis Date"
            }
        )

        history_chart.set_y_axis(
            {
                "name": "Commits"
            }
        )

        history_chart.set_legend(
            {
                "none": True
            }
        )

        history_chart.set_style(10)

        history_sheet.insert_chart(
            "G2",
            history_chart,
            {
                "x_scale": 1.3,
                "y_scale": 1.2,
            },
        )

    # ========================================================
    # Finish Workbook
    # ========================================================

    workbook.close()

    output.seek(0)

    filename = (
        f"FIS_Grader_{group_id}.xlsx"
    )

    return output, filename

# ============================================================
# Configuration Helpers
# ============================================================

def get_required_environment_variable(
    variable_name: str,
) -> str:
    """Return a required environment variable."""

    value = os.getenv(variable_name)

    if not value:
        raise RuntimeError(
            f"Environment variable {variable_name} is not set."
        )

    return value


def get_allowed_user_ids() -> set[int]:
    """Load authorized Telegram user IDs."""

    raw_value = os.getenv(
        ALLOWED_USERS_ENV,
        "",
    )

    allowed_users = set()

    for value in raw_value.split(","):
        value = value.strip()

        if not value:
            continue

        try:
            allowed_users.add(
                int(value)
            )

        except ValueError as error:
            raise RuntimeError(
                f"Invalid Telegram user ID: {value}"
            ) from error

    return allowed_users


# ============================================================
# MongoDB
# ============================================================

def create_mongodb_client() -> AsyncMongoClient:
    """Create an asynchronous MongoDB Atlas client."""

    mongodb_uri = get_required_environment_variable(
        MONGODB_URI_ENV
    )

    return AsyncMongoClient(
        mongodb_uri,
        server_api=ServerApi("1"),
        serverSelectionTimeoutMS=10_000,
    )


mongo_client = create_mongodb_client()

database = mongo_client[
    DATABASE_NAME
]


# ============================================================
# Authorization
# ============================================================

async def is_authorized(
    update: Update,
) -> bool:
    """Check whether the Telegram user can query grader data."""

    user = update.effective_user

    if user is None:
        return False

    allowed_users = get_allowed_user_ids()

    if user.id in allowed_users:
        return True

    if update.effective_message:
        await update.effective_message.reply_text(
            "You are not authorized to access grader data.\n\n"
            f"Your Telegram user ID is: {user.id}"
        )

    return False


# ============================================================
# General Commands
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Display the welcome message."""

    if update.effective_message is None:
        return

    await update.effective_message.reply_text(
        "FIS Grader Bot\n\n"
        "Repository activity information is available "
        "through the following commands:\n\n"
        "/groups\n"
        "/summary G1\n"
        "/commits G1\n"
        "/history G1\n"
        "/student email@example.com\n"
        "/ask ¿Cuál es el puntaje máximo de la rúbrica?\n"
        "/whoami"
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Display available commands."""

    await start_command(
        update,
        context,
    )


async def whoami_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Return the current Telegram user's numeric ID."""

    if (
        update.effective_user is None
        or update.effective_message is None
    ):
        return

    await update.effective_message.reply_text(
        "Your Telegram user ID is:\n"
        f"{update.effective_user.id}"
    )


# ============================================================
# Groups
# ============================================================

async def groups_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """List active course repositories."""

    if not await is_authorized(update):
        return

    cursor = (
        database.repositories
        .find(
            {
                "active": True
            }
        )
        .sort(
            "group_id",
            1,
        )
    )

    groups = []

    async for repository in cursor:
        groups.append(
            (
                f"{repository['group_id']} — "
                f"{repository['full_name']}"
            )
        )

    if not groups:
        message = (
            "No active repositories were found."
        )

    else:
        message = (
            "Active groups:\n\n"
            + "\n".join(groups)
        )

    await update.effective_message.reply_text(
        message
    )


# ============================================================
# Summary
# ============================================================

async def summary_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Display the latest summary for a group."""

    if not await is_authorized(update):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage:\n/summary G1"
        )
        return

    group_id = context.args[0].upper()

    repository = await database.repositories.find_one(
        {
            "group_id": group_id
        }
    )

    if repository is None:
        await update.effective_message.reply_text(
            f"Group {group_id} was not found."
        )
        return

    metrics = repository.get(
        "latest_metrics"
    )

    if not metrics:
        await update.effective_message.reply_text(
            f"No analysis data is available for {group_id}."
        )
        return

    last_analysis = repository.get(
        "last_analysis_at"
    )

    message = (
        f"📊 {group_id} Summary\n\n"
        f"Repository:\n"
        f"{repository['full_name']}\n\n"
        f"Commits in analysis period: "
        f"{metrics.get('period_commit_count', 0)}\n"
        f"Historical commits: "
        f"{metrics.get('historical_commit_count', 0)}\n"
        f"Active authors: "
        f"{metrics.get('period_author_count', 0)}"
    )

    if last_analysis:
        message += (
            "\n\nLast analysis:\n"
            f"{last_analysis.strftime('%Y-%m-%d %H:%M UTC')}"
        )

    await update.effective_message.reply_text(
        message
    )


# ============================================================
# Commits
# ============================================================

async def commits_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Display the latest commits for a group."""

    if not await is_authorized(update):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage:\n/commits G1 [limit]"
        )
        return

    group_id = context.args[0].upper()

    limit = DEFAULT_COMMIT_LIMIT

    if len(context.args) >= 2:
        try:
            limit = int(
                context.args[1]
            )

        except ValueError:
            await update.effective_message.reply_text(
                "The commit limit must be a number."
            )
            return

    limit = max(
        1,
        min(
            limit,
            MAX_COMMIT_LIMIT,
        ),
    )

    repository = await database.repositories.find_one(
        {
            "group_id": group_id
        }
    )

    if repository is None:
        await update.effective_message.reply_text(
            f"Group {group_id} was not found."
        )
        return

    cursor = (
        database.commits
        .find(
            {
                "repository_id": repository["_id"]
            }
        )
        .sort(
            "date",
            DESCENDING,
        )
        .limit(limit)
    )

    commits = []

    async for commit in cursor:

        date = commit.get("date")

        if date:
            formatted_date = date.strftime(
                "%Y-%m-%d"
            )
        else:
            formatted_date = "Unknown date"

        commits.append(
            (
                f"• {commit.get('short_hash', '')}\n"
                f"  {commit.get('author_name', 'Unknown')}\n"
                f"  {formatted_date}\n"
                f"  {commit.get('message', '')}"
            )
        )

    if not commits:
        message = (
            f"No commits were found for {group_id}."
        )

    else:
        message = (
            f"Latest commits — {group_id}\n\n"
            + "\n\n".join(commits)
        )

    await update.effective_message.reply_text(
        message
    )


# ============================================================
# History
# ============================================================

async def history_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Display historical weekly snapshots for a group."""

    if not await is_authorized(update):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage:\n/history G1"
        )
        return

    group_id = context.args[0].upper()

    cursor = (
        database.analysis_runs
        .find(
            {
                "group_id": group_id
            }
        )
        .sort(
            "executed_at",
            DESCENDING,
        )
        .limit(10)
    )

    runs = []

    async for analysis in cursor:

        executed_at = analysis.get(
            "executed_at"
        )

        metrics = analysis.get(
            "metrics",
            {},
        )

        date_text = (
            executed_at.strftime("%Y-%m-%d")
            if executed_at
            else "Unknown"
        )

        runs.append(
            (
                f"{date_text}: "
                f"{metrics.get('period_commit_count', 0)} commits, "
                f"{metrics.get('period_author_count', 0)} authors"
            )
        )

    if not runs:
        message = (
            f"No historical analyses were found for {group_id}."
        )

    else:
        message = (
            f"📈 {group_id} History\n\n"
            + "\n".join(runs)
        )

    await update.effective_message.reply_text(
        message
    )


# ============================================================
# Student
# ============================================================

async def student_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Display stored information for an author email."""

    if not await is_authorized(update):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage:\n/student email@example.com"
        )
        return

    email = context.args[0].strip().lower()

    author = await database.authors.find_one(
        {
            "email": email
        }
    )

    if author is None:
        await update.effective_message.reply_text(
            f"No author was found with email:\n{email}"
        )
        return

    commit_count = await database.commits.count_documents(
        {
            "author_id": author["_id"]
        }
    )

    names = author.get(
        "names_used",
        [],
    )

    names_text = (
        ", ".join(names)
        if names
        else "Unknown"
    )

    message = (
        "👤 Author\n\n"
        f"Email:\n{email}\n\n"
        f"Names used:\n{names_text}\n\n"
        f"Stored commits: {commit_count}"
    )

    await update.effective_message.reply_text(
        message
    )

# ============================================================
# Excel Report
# ============================================================

async def excel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Generate and send an Excel report for a course group.

    Usage:
        /excel G1
    """

    if not await is_authorized(update):
        return

    if update.effective_message is None:
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage:\n/excel G1"
        )
        return

    group_id = (
        context.args[0]
        .strip()
        .upper()
    )

    await update.effective_message.reply_text(
        f"📊 Generating Excel report for {group_id}..."
    )

    try:
        excel_file, filename = await generate_group_excel(
            group_id
        )

    except ValueError as error:
        await update.effective_message.reply_text(
            str(error)
        )
        return

    except Exception:
        LOGGER.exception(
            "Failed to generate Excel report for %s.",
            group_id,
        )

        await update.effective_message.reply_text(
            "An error occurred while generating the Excel report."
        )
        return

    await update.effective_message.reply_document(
        document=excel_file,
        filename=filename,
        caption=(
            f"📈 FIS Grader Report — {group_id}\n"
            "Generated from the latest MongoDB data."
        ),
    )


# ============================================================
# Rubric RAG
# ============================================================

async def ask_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Answer a question using the locally indexed grading rubric."""

    if not await is_authorized(update):
        return

    if update.effective_message is None:
        return

    question = " ".join(context.args).strip()
    if not question:
        await update.effective_message.reply_text(
            "Usage:\n/ask ¿Cuál es el puntaje máximo de la rúbrica?"
        )
        return

    try:
        # RAG dependencies/configuration failures must not prevent bot startup.
        from src.rag.service import ask_rag
        from src.rag.ollama import OllamaError

        try:
            answer = await ask_rag(question)
        except OllamaError as error:
            await update.effective_message.reply_text(str(error))
            return

    except ValueError as error:
        await update.effective_message.reply_text(str(error))
        return

    except RuntimeError as error:
        LOGGER.warning("RAG request could not be completed: %s", error)
        await update.effective_message.reply_text(
            "No puedo consultar la rúbrica todavía. "
            "Verifica que el índice esté creado y que Ollama esté disponible con GPU."
        )
        return

    except Exception:
        LOGGER.exception("Failed to answer RAG question.")
        await update.effective_message.reply_text(
            "Ocurrió un error al consultar la rúbrica."
        )
        return

    # Stay below Telegram's 4096-character limit, including astral Unicode.
    for offset in range(0, len(answer), 2000):
        await update.effective_message.reply_text(answer[offset:offset + 2000])


# ============================================================
# Error Handler
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Log unexpected Telegram bot errors."""

    LOGGER.exception(
        "Unhandled Telegram bot error.",
        exc_info=context.error,
    )


# ============================================================
# Application
# ============================================================

async def post_init(
    application: Application,
) -> None:
    """Verify MongoDB connectivity when the bot starts."""

    await mongo_client.admin.command(
        "ping"
    )

    LOGGER.info(
        "MongoDB connection established."
    )


def main() -> None:
    """Start the Telegram bot."""

    telegram_token = (
        get_required_environment_variable(
            TELEGRAM_TOKEN_ENV
        )
    )

    application = (
        Application.builder()
        .token(telegram_token)
        .post_init(post_init)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "whoami",
            whoami_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "groups",
            groups_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "summary",
            summary_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "commits",
            commits_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "history",
            history_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "student",
            student_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "excel",
            excel_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "ask",
            ask_command,
        )
    )

    application.add_error_handler(
        error_handler
    )

    LOGGER.info(
        "FIS Grader Telegram Bot started."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()

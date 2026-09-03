"""
Automated Student Code Grader.

This script validates the required files in a student repository,
evaluates their contents against a rubric using the DeepSeek API,
and stores the generated evaluations in a JSON report.
"""

import argparse
import json
import os
from pathlib import Path

from openai import OpenAI


# ============================================================
# Configuration
# ============================================================

RUBRIC_PATH = Path("grader/.github/classroom/rubric.md")
OUTPUT_FILE = Path("result.json")

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"


# ============================================================
# Command-Line Arguments
# ============================================================

def parse_arguments() -> argparse.Namespace:
    """
    Parse and return command-line arguments.

    Returns:
        argparse.Namespace: Parsed command-line arguments.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Evaluate required files from a student repository "
            "using an LLM-based grader."
        )
    )

    parser.add_argument(
        "--repository",
        type=Path,
        required=True,
        help="Path to the student repository.",
    )

    parser.add_argument(
        "--required-files",
        type=str,
        required=True,
        help=(
            "Comma-separated list of files that must exist "
            "inside the student repository."
        ),
    )

    return parser.parse_args()


# ============================================================
# File Validation
# ============================================================

def parse_required_files(required_files: str) -> list[str]:
    """
    Convert the comma-separated required-files argument into a list.

    Args:
        required_files: Comma-separated file paths.

    Returns:
        List of normalized file paths.
    """

    return [
        file_path.strip()
        for file_path in required_files.split(",")
        if file_path.strip()
    ]


def validate_required_files(
    repository_path: Path,
    required_files: list[str],
) -> None:
    """
    Verify that every required file exists in the repository.

    Args:
        repository_path: Path to the student repository.
        required_files: Files expected to exist in the repository.

    Raises:
        FileNotFoundError: If one or more required files are missing.
    """

    missing_files = [
        file_path
        for file_path in required_files
        if not (repository_path / file_path).is_file()
    ]

    if missing_files:
        formatted_files = "\n".join(
            f"  - {file_path}"
            for file_path in missing_files
        )

        raise FileNotFoundError(
            "The following required files were not found:\n"
            f"{formatted_files}"
        )


# ============================================================
# Rubric
# ============================================================

def load_rubric(rubric_path: Path) -> str:
    """
    Load the grading rubric from disk.

    Args:
        rubric_path: Path to the rubric file.

    Returns:
        Rubric contents as text.

    Raises:
        FileNotFoundError: If the rubric file does not exist.
    """

    if not rubric_path.is_file():
        raise FileNotFoundError(
            f"Rubric file not found: {rubric_path}"
        )

    return rubric_path.read_text(encoding="utf-8")


# ============================================================
# DeepSeek Client
# ============================================================

def create_deepseek_client() -> OpenAI:
    """
    Create and configure the DeepSeek API client.

    DeepSeek exposes an OpenAI-compatible API, allowing the
    official OpenAI Python SDK to be used with a custom base URL.

    Returns:
        Configured OpenAI client.

    Raises:
        RuntimeError: If the DeepSeek API key is not configured.
    """

    api_key = os.getenv(DEEPSEEK_API_KEY_ENV)

    if not api_key:
        raise RuntimeError(
            f"Environment variable {DEEPSEEK_API_KEY_ENV} is not set."
        )

    return OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
    )


# ============================================================
# File Evaluation
# ============================================================

def evaluate_file(
    client: OpenAI,
    rubric: str,
    repository_path: Path,
    file_path: str,
) -> dict[str, str]:
    """
    Evaluate a source file using the grading rubric.

    Args:
        client: Configured DeepSeek API client.
        rubric: Grading rubric used as the system prompt.
        repository_path: Path to the student repository.
        file_path: Relative path of the file to evaluate.

    Returns:
        Dictionary containing the evaluated file and LLM response.
    """

    full_path = repository_path / file_path

    source_code = full_path.read_text(
        encoding="utf-8"
    )

    messages = [
        {
            "role": "system",
            "content": rubric,
        },
        {
            "role": "user",
            "content": (
                "Evaluate the following student file according "
                "to the provided rubric.\n\n"
                f"File: {file_path}\n\n"
                "----- BEGIN STUDENT FILE -----\n"
                f"{source_code}\n"
                "----- END STUDENT FILE -----"
            ),
        },
    ]

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=messages,
        stream=False,
    )

    llm_response = response.choices[0].message.content

    if llm_response is None:
        raise RuntimeError(
            f"The model returned an empty response for {file_path}."
        )

    return {
        "evaluated_file": file_path,
        "llm_response": llm_response,
    }


# ============================================================
# Report
# ============================================================

def save_results(
    results: list[dict[str, str]],
    output_path: Path,
) -> None:
    """
    Save all evaluation results to a JSON file.

    Args:
        results: Evaluation results to save.
        output_path: Destination JSON file.
    """

    report = {
        "evaluations": results,
    }

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as output_file:
        json.dump(
            report,
            output_file,
            indent=4,
            ensure_ascii=False,
        )


# ============================================================
# Main Program
# ============================================================

def main() -> None:
    """Run the complete grading process."""

    args = parse_arguments()

    repository_path = args.repository

    required_files = parse_required_files(
        args.required_files
    )

    if not required_files:
        raise ValueError(
            "At least one required file must be provided."
        )

    # Validate all required files before making any API requests.
    validate_required_files(
        repository_path,
        required_files,
    )

    rubric = load_rubric(
        RUBRIC_PATH
    )

    client = create_deepseek_client()

    results = []

    for file_path in required_files:

        print(
            f"\nEvaluating: {file_path}"
        )

        result = evaluate_file(
            client,
            rubric,
            repository_path,
            file_path,
        )

        results.append(result)

        print(
            "\n=========================================="
        )
        print(
            f"EVALUATION - {file_path}"
        )
        print(
            "=========================================="
        )
        print(
            result["llm_response"]
        )

    save_results(
        results,
        OUTPUT_FILE,
    )

    print(
        f"\nEvaluation report saved to: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
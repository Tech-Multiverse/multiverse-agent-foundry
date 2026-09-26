from pathlib import Path

import pytest

from src.tools.calculator_server import evaluate_expression
from src.tools.file_write_server import write_data_file


def test_calculator_evaluates_arithmetic_without_code_execution() -> None:
    assert evaluate_expression("(3 + 5) * 12") == 96
    with pytest.raises(ValueError, match="Only numeric literals"):
        evaluate_expression("__import__('os').getcwd()")


def test_file_write_is_restricted_to_data_directory(tmp_path: Path) -> None:
    target = write_data_file("result.md", "verified", tmp_path)

    assert Path(target).read_text(encoding="utf-8") == "verified"
    with pytest.raises(ValueError, match="must not contain a directory path"):
        write_data_file("../outside.md", "blocked", tmp_path)
    with pytest.raises(ValueError, match="must end"):
        write_data_file("script.py", "blocked", tmp_path)

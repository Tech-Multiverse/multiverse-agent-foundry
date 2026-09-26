from pathlib import Path
from typing import Any

import yaml

from src.config_schema import TaskConfig


def load_task_config(config_path: str | Path) -> TaskConfig:
    path = Path(config_path)
    with path.open(encoding="utf-8") as config_file:
        raw_config: Any = yaml.safe_load(config_file)

    if not isinstance(raw_config, dict):
        raise ValueError(f"Task config must be a mapping: {path}")

    return TaskConfig.model_validate(raw_config)

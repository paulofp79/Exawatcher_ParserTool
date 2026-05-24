from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


class PyLogger:
    def __init__(
        self,
        logger_name: str = "ExaWatcher",
        logger_re: str = "",
        log_dir: str = ".",
        filepath: str = "",
        tracepath: str = "",
        **_kwargs: Any,
    ) -> None:
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        target = filepath or log_dir
        target_path = Path(target).expanduser()
        self._log_dir = target_path if target_path.suffix == "" else target_path.parent
        self._log_dir.mkdir(parents=True, exist_ok=True)
        if not self.logger.handlers:
            log_file = target_path if target_path.suffix else self._log_dir / f"{logger_name}.log"
            handler = logging.FileHandler(log_file)
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.logger.addHandler(handler)

    def set_format(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_level(self, log_level: str, *_args: Any, **_kwargs: Any) -> None:
        level = getattr(logging, str(log_level).upper(), logging.INFO)
        self.logger.setLevel(level)

    def log_msg(self, msg: str, loglevel: str = "info", *_args: Any, **_kwargs: Any) -> None:
        level = getattr(logging, str(loglevel).upper(), logging.INFO)
        self.logger.log(level, msg)

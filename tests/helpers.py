from __future__ import annotations

import os
import tempfile
from pathlib import Path

from meme_collector_app.core.config import get_settings
from meme_collector_app.db.models import init_db


class TempDatabaseMixin:
    def setUp(self) -> None:
        super().setUp()
        self._saved_env = {
            key: os.environ.get(key)
            for key in (
                "DATABASE_PATH",
                "DIFY_SKIP_CHECK_FOR_DRY_RUN",
                "DIFY_DATASET_ID",
                "DIFY_API_KEY",
            )
        }
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = str(Path(self.tmpdir.name) / "test.sqlite3")
        os.environ.pop("DIFY_SKIP_CHECK_FOR_DRY_RUN", None)
        os.environ.pop("DIFY_DATASET_ID", None)
        os.environ.pop("DIFY_API_KEY", None)
        get_settings.cache_clear()
        init_db()

    def tearDown(self) -> None:
        get_settings.cache_clear()
        self.tmpdir.cleanup()
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        super().tearDown()

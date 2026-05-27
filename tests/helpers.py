from __future__ import annotations

import os
import tempfile
from pathlib import Path

from meme_collector_app.core.config import get_settings
from meme_collector_app.db.models import init_db


class TempDatabaseMixin:
    def setUp(self) -> None:
        super().setUp()
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = str(Path(self.tmpdir.name) / "test.sqlite3")
        get_settings.cache_clear()
        init_db()

    def tearDown(self) -> None:
        get_settings.cache_clear()
        self.tmpdir.cleanup()
        super().tearDown()

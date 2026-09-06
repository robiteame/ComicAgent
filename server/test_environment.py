"""Shared isolated environment for the server test suite.

Every test module imports this before importing application services.  Settings
are constructed from environment variables, so the module import order must not
be allowed to bind tests to the repository's real runtime directories.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path


TEST_ROOT = Path(tempfile.mkdtemp(prefix="comic-agent-tests-"))

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'comic-agent.db'}"
os.environ["DATA_DIR"] = str(TEST_ROOT / "data")
os.environ["OUTPUT_DIR"] = str(TEST_ROOT / "output")
os.environ["CHROMADB_PATH"] = str(TEST_ROOT / "chromadb")
os.environ["CHECKPOINT_PATH"] = str(TEST_ROOT / "checkpoints")
os.environ["IMAGE_PROVIDER"] = "local"

atexit.register(shutil.rmtree, TEST_ROOT, ignore_errors=True)


"""Immutable bundled resources and configurable per-user storage."""
import os
import sys
from pathlib import Path

RESOURCE_ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))
WEB_ROOT=RESOURCE_ROOT/'web' if getattr(sys,'frozen',False) else Path(__file__).parent/'web'
DEFAULT_HOME=Path.home()/'JunZhenMatch'
CONFIG_ROOT=Path(os.getenv('JZ_CONFIG_DIR') or os.getenv('JZ_DATA_DIR') or DEFAULT_HOME).expanduser().resolve()
SEED_DB=RESOURCE_ROOT/'data/faculty.db'


def data_identity(path):
    import hashlib
    return hashlib.sha256(os.path.normcase(str(Path(path).resolve())).encode()).hexdigest()

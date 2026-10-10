"""SQLite engine, schema creation and append-only guards."""
from __future__ import annotations

from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401 - register tables
from app.config import settings

_engine = None

# Snapshots can never be updated. Only simulated backtest snapshots may be
# deleted (so build_history.py can be re-run); live/replay/livecheck rows and
# all human decisions are permanent.
IMMUTABLE_TRIGGERS = [
    """CREATE TRIGGER IF NOT EXISTS notificationaudit_no_update BEFORE UPDATE ON notificationaudit
       BEGIN SELECT RAISE(ABORT, 'notification audit is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS notificationaudit_no_delete BEFORE DELETE ON notificationaudit
       BEGIN SELECT RAISE(ABORT, 'notification audit is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS snapshot_no_update BEFORE UPDATE ON snapshot
       BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END""",
    """CREATE TRIGGER IF NOT EXISTS snapshot_no_delete BEFORE DELETE ON snapshot
       WHEN OLD.mode != 'backtest'
       BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END""",
    """CREATE TRIGGER IF NOT EXISTS decision_no_update BEFORE UPDATE ON decision
       BEGIN SELECT RAISE(ABORT, 'decisions are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS decision_no_delete BEFORE DELETE ON decision
       BEGIN SELECT RAISE(ABORT, 'decisions are append-only'); END""",
]


def make_engine(url: str):
    eng = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _):  # noqa: ANN001
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(eng)
    with eng.begin() as conn:
        for t in IMMUTABLE_TRIGGERS:
            conn.execute(text(t))
    return eng


def get_engine():
    global _engine
    if _engine is None:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = make_engine(f"sqlite:///{settings.db_path.as_posix()}")
    return _engine


def set_engine(eng) -> None:
    """Point the app at another engine (tests)."""
    global _engine
    _engine = eng


def session() -> Session:
    return Session(get_engine())

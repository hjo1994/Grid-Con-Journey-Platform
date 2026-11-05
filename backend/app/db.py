"""Access to the shared SQLite file.

Reads go through a read-only engine (``mode=ro``). The only write path is the
evaluators' input into the Bronze table UserEvaluationInputs, through a
separate read-write engine (``mode=rw``, never creates the file). Input
Orchestration writes in place with SQLite transactions; SQLite serialises
both writers via the file lock (busy timeout below), readers never see a
half-written state.

Every request opens the file fresh (NullPool): cheap for SQLite and still
correct should the file ever be replaced (older Input Orchestration versions
swapped it with an atomic rename). Opening can fail briefly while the file is
being replaced or locked, hence the short retry.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

_RETRIES = 3
_BACKOFF_SECONDS = 0.1


_BUSY_TIMEOUT_SECONDS = 10.0


def make_engine(db_path: Path, mode: str = "ro") -> Engine:
    uri = f"file:{quote(str(db_path))}?mode={mode}"
    return create_engine(
        "sqlite://",
        # FastAPI opens the session in the dependency and runs sync endpoints
        # in another threadpool thread. Safe: with NullPool each connection
        # belongs to exactly one request and is never shared.
        creator=lambda: sqlite3.connect(
            uri, uri=True, check_same_thread=False, timeout=_BUSY_TIMEOUT_SECONDS
        ),
        poolclass=NullPool,
    )


def open_session(engine: Engine) -> Session:
    for attempt in range(_RETRIES):
        session = Session(engine)
        try:
            session.execute(text("SELECT 1 FROM GridConnectionRequests LIMIT 1"))
            return session
        except OperationalError:
            session.close()
            if attempt == _RETRIES - 1:
                raise
            time.sleep(_BACKOFF_SECONDS * (attempt + 1))
    raise AssertionError("unreachable")


def get_session(request: Request):
    session = open_session(request.app.state.engine)
    try:
        yield session
    finally:
        session.close()


def get_write_session(request: Request):
    """Session on the read-write engine; used only for UserEvaluationInputs."""
    session = open_session(request.app.state.write_engine)
    try:
        yield session
    finally:
        session.close()

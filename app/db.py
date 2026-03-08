"""Dependency: connexió SQLite per petició (obrir i tancar)."""
import sqlite3
from collections.abc import Generator

from fastapi import Depends, HTTPException

from app.config import database_path


def get_db() -> Generator[sqlite3.Connection, None, None]:
    if not database_path.is_file():
        raise HTTPException(
            status_code=503,
            detail=f"Base de dades no trobada: {database_path}. Defineix DATABASE_PATH o col·loca arxiu_discs.db a data/.",
        )
    # check_same_thread=False perquè FastAPI executa els handlers síncrons en un thread pool
    conn = sqlite3.connect(str(database_path), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

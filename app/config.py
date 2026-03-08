"""Configuració: ruta de la base de dades (variable d'entorn DATABASE_PATH o default)."""
import os
from pathlib import Path

# Arrel del projecte = directori pare de app/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# DB en directori separat (data/)
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "arxiu_discs.db"

database_path: Path = Path(os.environ.get("DATABASE_PATH", "")).resolve() if os.environ.get("DATABASE_PATH") else DEFAULT_DB_PATH

if not database_path.is_file():
    # No fallar aquí per permetre arrencar; les rutes retornaran error si no hi ha DB
    pass

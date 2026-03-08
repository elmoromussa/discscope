"""
Audit directe a la base de dades: recórrer una carpeta arrel i escriure
a SQLite sense CSV intermedis. Dissenyat per discs grans (5–8 TB, molts fitxers)
amb memòria fitada (buffer per chunks d'inventory).
"""
import csv
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Mida del buffer d'inventory abans de fer executemany (memòria fitada per a discs grans)
INVENTORY_CHUNK_SIZE = 10_000


def _utc_iso(dt_ts: float) -> str:
    """Converteix timestamp Unix a ISO UTC. Retorna '' si invàlid."""
    try:
        return datetime.fromtimestamp(dt_ts, tz=timezone.utc).isoformat()
    except (OSError, ValueError, OverflowError):
        return ""


def init_schema(conn: sqlite3.Connection) -> None:
    """Crea les taules i índexs si no existixen. Inclou migració folder_name."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drive_id TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            name TEXT NOT NULL,
            extension TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            modified_utc TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_inventory_drive ON inventory(drive_id);
        CREATE INDEX IF NOT EXISTS idx_inventory_extension ON inventory(drive_id, extension);
        CREATE INDEX IF NOT EXISTS idx_inventory_name ON inventory(name);

        CREATE TABLE IF NOT EXISTS folder_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drive_id TEXT NOT NULL,
            folder_path TEXT NOT NULL,
            folder_name TEXT,
            folder_depth INTEGER,
            files_count INTEGER NOT NULL,
            total_bytes INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_folder_stats_drive ON folder_stats(drive_id);
        CREATE INDEX IF NOT EXISTS idx_folder_stats_folder_name ON folder_stats(folder_name);

        CREATE TABLE IF NOT EXISTS by_extension (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drive_id TEXT NOT NULL,
            extension TEXT NOT NULL,
            count INTEGER NOT NULL,
            total_bytes INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_by_extension_drive ON by_extension(drive_id);
    """)
    try:
        conn.execute("ALTER TABLE folder_stats ADD COLUMN folder_name TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_folder_stats_folder_name ON folder_stats(folder_name)")
    except sqlite3.OperationalError:
        pass


def audit_direct_to_db(
    conn: sqlite3.Connection,
    root_path: Path,
    drive_id: str,
    replace: bool,
) -> tuple[int, int, int]:
    """
    Audita la carpeta arrel i escriu directament a la DB (inventory, folder_stats, by_extension).
    Memòria fitada: inventory en chunks, folder_stats i by_extension en diccionaris.
    Una sola transacció (commit al final).
    Retorna (inventory_rows, folder_stats_rows, by_extension_rows).
    """
    root_path = root_path.resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(f"No és un directori: {root_path}")

    if replace:
        conn.execute("DELETE FROM inventory WHERE drive_id = ?", (drive_id,))
        conn.execute("DELETE FROM folder_stats WHERE drive_id = ?", (drive_id,))
        conn.execute("DELETE FROM by_extension WHERE drive_id = ?", (drive_id,))

    ext_stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_bytes": 0})
    folder_agg: dict[str, dict] = defaultdict(lambda: {"files_count": 0, "total_bytes": 0})
    inv_chunk: list[tuple] = []

    def flush_inventory() -> None:
        if not inv_chunk:
            return
        conn.executemany(
            "INSERT INTO inventory (drive_id, relative_path, name, extension, size_bytes, modified_utc) VALUES (?, ?, ?, ?, ?, ?)",
            inv_chunk,
        )
        inv_chunk.clear()

    inv_count = 0
    for dirpath, _dirnames, filenames in os.walk(root_path):
        d = Path(dirpath)
        for fn in filenames:
            p = d / fn
            try:
                st = p.stat()
            except OSError:
                continue
            try:
                rel = p.relative_to(root_path)
            except ValueError:
                continue
            ext = p.suffix.lower() if p.suffix else "(no_ext)"
            mtime_str = _utc_iso(st.st_mtime)
            inv_chunk.append((drive_id, str(rel), p.name, ext, st.st_size, mtime_str))
            inv_count += 1
            ext_stats[ext]["count"] += 1
            ext_stats[ext]["total_bytes"] += st.st_size
            folder_agg[str(d)]["files_count"] += 1
            folder_agg[str(d)]["total_bytes"] += st.st_size
            if len(inv_chunk) >= INVENTORY_CHUNK_SIZE:
                flush_inventory()
    flush_inventory()

    # Inserir folder_stats
    folder_rows: list[tuple] = []
    for folder_path, v in folder_agg.items():
        fp = Path(folder_path)
        try:
            rel = fp.relative_to(root_path)
            depth = len(rel.parts)
        except (ValueError, TypeError):
            depth = None
        folder_name_val = fp.name if fp.name else ""
        folder_rows.append((drive_id, folder_path, folder_name_val, depth, v["files_count"], v["total_bytes"]))
    if folder_rows:
        conn.executemany(
            "INSERT INTO folder_stats (drive_id, folder_path, folder_name, folder_depth, files_count, total_bytes) VALUES (?, ?, ?, ?, ?, ?)",
            folder_rows,
        )
    folder_count = len(folder_rows)

    # Inserir by_extension
    ext_rows = [(drive_id, ext, v["count"], v["total_bytes"]) for ext, v in ext_stats.items()]
    if ext_rows:
        conn.executemany(
            "INSERT INTO by_extension (drive_id, extension, count, total_bytes) VALUES (?, ?, ?, ?)",
            ext_rows,
        )
    ext_count = len(ext_rows)

    conn.commit()
    return inv_count, folder_count, ext_count


def import_from_csv_folder(
    conn: sqlite3.Connection,
    audit_dir: Path,
    drive_id: str,
    replace: bool,
) -> tuple[int, int, int]:
    """
    Importa des d'una carpeta d'audit existent (inventory_files.csv, folders_stats.csv, by_extension.csv).
    Per compatibilitat amb audits generats externament. Retorna (inv_count, folder_count, ext_count).
    """
    audit_dir = audit_dir.resolve()
    if not audit_dir.is_dir():
        raise NotADirectoryError(f"No és un directori: {audit_dir}")
    inv_path = audit_dir / "inventory_files.csv"
    if not inv_path.exists():
        raise FileNotFoundError(f"Falta inventory_files.csv a {audit_dir}")

    if replace:
        conn.execute("DELETE FROM inventory WHERE drive_id = ?", (drive_id,))
        conn.execute("DELETE FROM folder_stats WHERE drive_id = ?", (drive_id,))
        conn.execute("DELETE FROM by_extension WHERE drive_id = ?", (drive_id,))

    inv_count = 0
    with inv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [
            (drive_id, row["RelativePath"], row["Name"], row["Extension"], int(row["SizeBytes"]), row.get("ModifiedUtc", ""))
            for row in reader
        ]
    if rows:
        conn.executemany(
            "INSERT INTO inventory (drive_id, relative_path, name, extension, size_bytes, modified_utc) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
    inv_count = len(rows)

    folder_path = audit_dir / "folders_stats.csv"
    folder_count = 0
    if folder_path.exists():
        with folder_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                fp = row["FolderPath"]
                folder_name_val = Path(fp).name if fp.strip() else ""
                rows.append(
                    (
                        drive_id,
                        fp,
                        folder_name_val,
                        int(row["FolderDepth"]) if row.get("FolderDepth") and str(row.get("FolderDepth", "")).strip() else None,
                        int(row["FilesCount"]),
                        int(row["TotalBytes"]),
                    )
                )
        if rows:
            conn.executemany(
                "INSERT INTO folder_stats (drive_id, folder_path, folder_name, folder_depth, files_count, total_bytes) VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
        folder_count = len(rows)

    ext_path = audit_dir / "by_extension.csv"
    ext_count = 0
    if ext_path.exists():
        with ext_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [(drive_id, row["Extension"], int(row["Count"]), int(row["TotalBytes"])) for row in reader]
        if rows:
            conn.executemany(
                "INSERT INTO by_extension (drive_id, extension, count, total_bytes) VALUES (?, ?, ?, ?)",
                rows,
            )
        ext_count = len(rows)

    conn.commit()
    return inv_count, folder_count, ext_count

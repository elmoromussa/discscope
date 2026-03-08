"""Consultes SQL: dashboard, cerca, duplicats, llistats. Sempre LIMIT on inventory."""
import sqlite3
from typing import Any

# Llistes blanques per ordenació (evitar SQL injection)
SEARCH_INVENTORY_SORT_COLUMNS = frozenset(
    {"drive_id", "relative_path", "name", "extension", "size_bytes", "modified_utc"}
)
FOLDER_STATS_SORT_COLUMNS = frozenset(
    {"drive_id", "folder_path", "folder_depth", "files_count", "total_bytes"}
)


def _extension_match_values(extensions: list[str]) -> list[str]:
    """Retorna llista de valors per matcher extension (amb i sense punt) per compatibilitat amb la DB."""
    seen: set[str] = set()
    for e in extensions:
        if not e:
            continue
        seen.add(e)
        if not e.startswith("."):
            seen.add("." + e)
    return list(seen)


def get_drives_summary(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Total fitxers i bytes per disc (des de by_extension)."""
    cur = conn.execute("""
        SELECT drive_id, SUM(count) AS files, SUM(total_bytes) AS total_bytes
        FROM by_extension GROUP BY drive_id ORDER BY drive_id
    """)
    return [dict(row) for row in cur.fetchall()]


def get_top_extensions(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    """Top extensions globals (suma de tots els discs)."""
    cur = conn.execute("""
        SELECT extension, SUM(count) AS total_count, SUM(total_bytes) AS total_bytes
        FROM by_extension GROUP BY extension ORDER BY total_count DESC LIMIT ?
    """, (limit,))
    return [dict(row) for row in cur.fetchall()]


def get_top_folders(conn: sqlite3.Connection, limit: int = 30) -> list[dict[str, Any]]:
    """Top carpetes per total_bytes (folder_stats)."""
    cur = conn.execute("""
        SELECT drive_id, folder_path, folder_depth, files_count, total_bytes
        FROM folder_stats ORDER BY total_bytes DESC LIMIT ?
    """, (limit,))
    return [dict(row) for row in cur.fetchall()]


SEARCH_SCOPE_VALUES = ("name", "path", "both")


def _user_to_like_pattern(q: str) -> str:
    """
    Converteix la paraula clau de l'usuari en un patró LIKE per a SQL.
    * -> % (qualsevol seqüència), ? -> _ (un caràcter). Si no hi ha * o % al començament/final, s'afegeix %.
    """
    if not q:
        return "%"
    s = q.replace("*", "%").replace("?", "_")
    if not s.startswith("%"):
        s = "%" + s
    if not s.endswith("%"):
        s = s + "%"
    return s


def _build_search_inventory_where(
    drive_ids: list[str] | None,
    term: str,
    min_size_bytes: int,
    exclude_terms: list[str],
    extensions: list[str] | None = None,
    scope: str = "both",
) -> tuple[str, list]:
    """Construïx la clàusula WHERE i els paràmetres per search_inventory."""
    if scope not in SEARCH_SCOPE_VALUES:
        scope = "both"
    if scope == "name":
        conditions = ["(name LIKE ?)"]
        params: list = [term]
    elif scope == "path":
        conditions = ["(relative_path LIKE ?)"]
        params = [term]
    else:
        conditions = ["(name LIKE ? OR relative_path LIKE ?)"]
        params = [term, term]
    if drive_ids:
        placeholders = ",".join("?" * len(drive_ids))
        conditions.insert(0, f"drive_id IN ({placeholders})")
        params = list(drive_ids) + params
    if min_size_bytes > 0:
        conditions.append("size_bytes >= ?")
        params.append(min_size_bytes)
    if extensions:
        ext_values = _extension_match_values(extensions)
        placeholders = ",".join("?" * len(ext_values))
        conditions.append(f"extension IN ({placeholders})")
        params.extend(ext_values)
    for ex in exclude_terms:
        if not ex.strip():
            continue
        excl = _user_to_like_pattern(ex.strip())
        conditions.append("name NOT LIKE ? AND relative_path NOT LIKE ?")
        params.extend([excl, excl])
    where = " AND ".join(conditions)
    return where, params


def search_inventory(
    conn: sqlite3.Connection,
    q: str,
    drive_ids: list[str] | None,
    limit: int,
    offset: int,
    min_size_bytes: int = 0,
    exclude_terms: list[str] | None = None,
    extensions: list[str] | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    scope: str = "both",
) -> tuple[list[dict[str, Any]], int]:
    """Cerca en name i/o relative_path segons scope. Retorna (rows, total_count)."""
    exclude_terms = exclude_terms or []
    if scope not in SEARCH_SCOPE_VALUES:
        scope = "both"
    term = _user_to_like_pattern(q)
    where, params = _build_search_inventory_where(
        drive_ids, term, min_size_bytes, exclude_terms, extensions, scope
    )
    params_count = list(params)
    if sort_by and sort_by in SEARCH_INVENTORY_SORT_COLUMNS and sort_dir.lower() in ("asc", "desc"):
        order_dir = "ASC" if sort_dir.lower() == "asc" else "DESC"
        order_by = f"{sort_by} {order_dir}, drive_id, relative_path"
    else:
        order_by = "drive_id, relative_path"
    params.extend([limit, offset])
    cur = conn.execute(
        f"""
        SELECT id, drive_id, relative_path, name, extension, size_bytes, modified_utc
        FROM inventory
        WHERE {where}
        ORDER BY {order_by} LIMIT ? OFFSET ?
        """,
        params,
    )
    cur_count = conn.execute(f"SELECT COUNT(*) FROM inventory WHERE {where}", params_count)
    rows = [dict(row) for row in cur.fetchall()]
    total = cur_count.fetchone()[0]
    return rows, total


def _build_search_folders_where(
    drive_ids: list[str] | None,
    term: str,
    max_depth: int | None,
    min_size_bytes: int,
    exclude_terms: list[str],
) -> tuple[str, list]:
    """Construïx la clàusula WHERE i els paràmetres per search_folders."""
    conditions = ["folder_path LIKE ?"]
    params: list = [term]
    if drive_ids:
        placeholders = ",".join("?" * len(drive_ids))
        conditions.insert(0, f"drive_id IN ({placeholders})")
        params = list(drive_ids) + params
    if max_depth is not None:
        conditions.append("(folder_depth IS NULL OR folder_depth <= ?)")
        params.append(max_depth)
    if min_size_bytes > 0:
        conditions.append("total_bytes >= ?")
        params.append(min_size_bytes)
    for ex in exclude_terms:
        if not ex.strip():
            continue
        conditions.append("folder_path NOT LIKE ?")
        params.append(_user_to_like_pattern(ex.strip()))
    where = " AND ".join(conditions)
    return where, params


def search_folders(
    conn: sqlite3.Connection,
    q: str,
    drive_ids: list[str] | None,
    limit: int,
    offset: int,
    max_depth: int | None = None,
    min_size_bytes: int = 0,
    exclude_terms: list[str] | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[dict[str, Any]], int]:
    """Cerca en folder_path (folder_stats). Retorna (rows, total_count)."""
    exclude_terms = exclude_terms or []
    term = _user_to_like_pattern(q)
    where, params = _build_search_folders_where(
        drive_ids, term, max_depth, min_size_bytes, exclude_terms
    )
    params_count = list(params)
    if sort_by and sort_by in FOLDER_STATS_SORT_COLUMNS and sort_dir.lower() in ("asc", "desc"):
        order_dir = "ASC" if sort_dir.lower() == "asc" else "DESC"
        order_by = f"{sort_by} {order_dir}, drive_id, total_bytes DESC"
    else:
        order_by = "drive_id, total_bytes DESC"
    params.extend([limit, offset])
    cur = conn.execute(
        f"""
        SELECT drive_id, folder_path, folder_depth, files_count, total_bytes
        FROM folder_stats
        WHERE {where}
        ORDER BY {order_by} LIMIT ? OFFSET ?
        """,
        params,
    )
    cur_count = conn.execute(f"SELECT COUNT(*) FROM folder_stats WHERE {where}", params_count)
    rows = [dict(row) for row in cur.fetchall()]
    total = cur_count.fetchone()[0]
    return rows, total


def _build_duplicate_files_where(
    drive_ids: list[str] | None,
    min_size_bytes: int,
    extensions: list[str] | None,
    exclude_terms: list[str],
    include_terms: list[str] | None = None,
) -> tuple[str, list]:
    """Construïx la clàusula WHERE per duplicats de fitxers (inventory)."""
    conditions: list[str] = []
    params: list = []
    if drive_ids:
        placeholders = ",".join("?" * len(drive_ids))
        conditions.append(f"drive_id IN ({placeholders})")
        params.extend(drive_ids)
    if min_size_bytes > 0:
        conditions.append("size_bytes >= ?")
        params.append(min_size_bytes)
    if extensions:
        ext_values = _extension_match_values(extensions)
        placeholders = ",".join("?" * len(ext_values))
        conditions.append(f"extension IN ({placeholders})")
        params.extend(ext_values)
    include_terms = include_terms or []
    for inc in include_terms:
        if not inc.strip():
            continue
        incl = _user_to_like_pattern(inc.strip())
        conditions.append("(name LIKE ? OR relative_path LIKE ?)")
        params.extend([incl, incl])
    for ex in exclude_terms:
        if not ex.strip():
            continue
        excl = _user_to_like_pattern(ex.strip())
        conditions.append("name NOT LIKE ? AND relative_path NOT LIKE ?")
        params.extend([excl, excl])
    where = " AND ".join(conditions) if conditions else "1=1"
    return where, params


DUPLICATE_NAMES_SORT_COLUMNS = ("name", "ndrives", "total_files")
DUPLICATE_NAME_SIZE_SORT_COLUMNS = ("name", "size_bytes", "ndrives", "total_files")
DUPLICATE_FOLDERS_PATH_SORT_COLUMNS = ("folder_path", "ndrives", "total_folders")
DUPLICATE_FOLDERS_PATH_SIZE_SORT_COLUMNS = ("folder_path", "total_bytes", "ndrives", "total_folders")


def get_duplicate_names_groups(
    conn: sqlite3.Connection,
    limit: int,
    offset: int,
    drive_ids: list[str] | None = None,
    min_size_bytes: int = 0,
    extensions: list[str] | None = None,
    exclude_terms: list[str] | None = None,
    include_terms: list[str] | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[dict[str, Any]], int]:
    """Grups amb mateix name en més d'un drive_id. Retorna (grups, total_grups)."""
    exclude_terms = exclude_terms or []
    where, params = _build_duplicate_files_where(
        drive_ids, min_size_bytes, extensions, exclude_terms, include_terms
    )
    base_sql = f"FROM inventory WHERE {where}"
    if sort_by and sort_by in DUPLICATE_NAMES_SORT_COLUMNS and sort_dir.lower() in ("asc", "desc"):
        order_dir = "ASC" if sort_dir.lower() == "asc" else "DESC"
        order_by = f"{sort_by} {order_dir}, total_files DESC"
    else:
        order_by = "total_files DESC"
    cur = conn.execute(
        f"""
        SELECT name, COUNT(DISTINCT drive_id) AS ndrives, COUNT(*) AS total_files
        {base_sql}
        GROUP BY name HAVING COUNT(DISTINCT drive_id) > 1
        ORDER BY {order_by} LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )
    groups = [dict(row) for row in cur.fetchall()]
    cur_total = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT name {base_sql} GROUP BY name HAVING COUNT(DISTINCT drive_id) > 1)",
        params,
    )
    total = cur_total.fetchone()[0]
    return groups, total


def get_duplicate_name_files(
    conn: sqlite3.Connection, name: str, limit: int = 50
) -> list[dict[str, Any]]:
    """Fitxers d'un grup de duplicats per nom."""
    cur = conn.execute(
        """
        SELECT drive_id, relative_path, name, size_bytes, modified_utc
        FROM inventory WHERE name = ? ORDER BY drive_id, relative_path LIMIT ?
        """,
        (name, limit),
    )
    return [dict(row) for row in cur.fetchall()]


def get_duplicate_name_size_groups(
    conn: sqlite3.Connection,
    limit: int,
    offset: int,
    drive_ids: list[str] | None = None,
    min_size_bytes: int = 0,
    extensions: list[str] | None = None,
    exclude_terms: list[str] | None = None,
    include_terms: list[str] | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[dict[str, Any]], int]:
    """Grups amb mateix name i size_bytes en més d'un drive_id."""
    exclude_terms = exclude_terms or []
    where, params = _build_duplicate_files_where(
        drive_ids, min_size_bytes, extensions, exclude_terms, include_terms
    )
    base_sql = f"FROM inventory WHERE {where}"
    if sort_by and sort_by in DUPLICATE_NAME_SIZE_SORT_COLUMNS and sort_dir.lower() in ("asc", "desc"):
        order_dir = "ASC" if sort_dir.lower() == "asc" else "DESC"
        order_by = f"{sort_by} {order_dir}, total_files DESC"
    else:
        order_by = "total_files DESC"
    cur = conn.execute(
        f"""
        SELECT name, size_bytes, COUNT(DISTINCT drive_id) AS ndrives, COUNT(*) AS total_files
        {base_sql}
        GROUP BY name, size_bytes HAVING COUNT(DISTINCT drive_id) > 1
        ORDER BY {order_by} LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )
    groups = [dict(row) for row in cur.fetchall()]
    cur_total = conn.execute(
        f"""
        SELECT COUNT(*) FROM (
            SELECT name, size_bytes {base_sql}
            GROUP BY name, size_bytes HAVING COUNT(DISTINCT drive_id) > 1
        )
        """,
        params,
    )
    total = cur_total.fetchone()[0]
    return groups, total


def get_duplicate_name_size_files(
    conn: sqlite3.Connection, name: str, size_bytes: int, limit: int = 50
) -> list[dict[str, Any]]:
    """Fitxers d'un grup de duplicats per nom+mida."""
    cur = conn.execute(
        """
        SELECT drive_id, relative_path, name, size_bytes, modified_utc
        FROM inventory WHERE name = ? AND size_bytes = ?
        ORDER BY drive_id, relative_path LIMIT ?
        """,
        (name, size_bytes, limit),
    )
    return [dict(row) for row in cur.fetchall()]


def _build_duplicate_folders_where(
    drive_ids: list[str] | None,
    max_depth: int | None,
    min_size_bytes: int,
    exclude_terms: list[str],
    include_terms: list[str] | None = None,
) -> tuple[str, list]:
    """Construïx la clàusula WHERE per duplicats de carpetes (folder_stats)."""
    conditions: list[str] = []
    params: list = []
    if drive_ids:
        placeholders = ",".join("?" * len(drive_ids))
        conditions.append(f"drive_id IN ({placeholders})")
        params.extend(drive_ids)
    if max_depth is not None:
        conditions.append("(folder_depth IS NULL OR folder_depth <= ?)")
        params.append(max_depth)
    if min_size_bytes > 0:
        conditions.append("total_bytes >= ?")
        params.append(min_size_bytes)
    include_terms = include_terms or []
    for inc in include_terms:
        if not inc.strip():
            continue
        conditions.append("folder_path LIKE ?")
        params.append(_user_to_like_pattern(inc.strip()))
    for ex in exclude_terms:
        if not ex.strip():
            continue
        conditions.append("folder_path NOT LIKE ?")
        params.append(_user_to_like_pattern(ex.strip()))
    where = " AND ".join(conditions) if conditions else "1=1"
    return where, params


def get_duplicate_folders_by_path_groups(
    conn: sqlite3.Connection,
    limit: int,
    offset: int,
    drive_ids: list[str] | None = None,
    max_depth: int | None = None,
    min_size_bytes: int = 0,
    exclude_terms: list[str] | None = None,
    include_terms: list[str] | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[dict[str, Any]], int]:
    """Grups de carpetes amb mateix folder_path en més d'un drive_id."""
    exclude_terms = exclude_terms or []
    where, params = _build_duplicate_folders_where(
        drive_ids, max_depth, min_size_bytes, exclude_terms, include_terms
    )
    base_sql = f"FROM folder_stats WHERE {where}"
    if sort_by and sort_by in DUPLICATE_FOLDERS_PATH_SORT_COLUMNS and sort_dir.lower() in ("asc", "desc"):
        order_dir = "ASC" if sort_dir.lower() == "asc" else "DESC"
        order_by = f"{sort_by} {order_dir}, total_folders DESC"
    else:
        order_by = "total_folders DESC"
    cur = conn.execute(
        f"""
        SELECT folder_path, COUNT(DISTINCT drive_id) AS ndrives, COUNT(*) AS total_folders
        {base_sql}
        GROUP BY folder_path HAVING COUNT(DISTINCT drive_id) > 1
        ORDER BY {order_by} LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )
    groups = [dict(row) for row in cur.fetchall()]
    cur_total = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT folder_path {base_sql} GROUP BY folder_path HAVING COUNT(DISTINCT drive_id) > 1)",
        params,
    )
    total = cur_total.fetchone()[0]
    return groups, total


def get_duplicate_folders_by_path_size_groups(
    conn: sqlite3.Connection,
    limit: int,
    offset: int,
    drive_ids: list[str] | None = None,
    max_depth: int | None = None,
    min_size_bytes: int = 0,
    exclude_terms: list[str] | None = None,
    include_terms: list[str] | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[dict[str, Any]], int]:
    """Grups de carpetes amb mateix folder_path i total_bytes en més d'un drive_id."""
    exclude_terms = exclude_terms or []
    where, params = _build_duplicate_folders_where(
        drive_ids, max_depth, min_size_bytes, exclude_terms, include_terms
    )
    base_sql = f"FROM folder_stats WHERE {where}"
    if sort_by and sort_by in DUPLICATE_FOLDERS_PATH_SIZE_SORT_COLUMNS and sort_dir.lower() in ("asc", "desc"):
        order_dir = "ASC" if sort_dir.lower() == "asc" else "DESC"
        order_by = f"{sort_by} {order_dir}, total_folders DESC"
    else:
        order_by = "total_folders DESC"
    cur = conn.execute(
        f"""
        SELECT folder_path, total_bytes, COUNT(DISTINCT drive_id) AS ndrives, COUNT(*) AS total_folders
        {base_sql}
        GROUP BY folder_path, total_bytes HAVING COUNT(DISTINCT drive_id) > 1
        ORDER BY {order_by} LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )
    groups = [dict(row) for row in cur.fetchall()]
    cur_total = conn.execute(
        f"""
        SELECT COUNT(*) FROM (
            SELECT folder_path, total_bytes {base_sql}
            GROUP BY folder_path, total_bytes HAVING COUNT(DISTINCT drive_id) > 1
        )
        """,
        params,
    )
    total = cur_total.fetchone()[0]
    return groups, total


def get_duplicate_folder_by_path_entries(
    conn: sqlite3.Connection, folder_path: str, limit: int = 50
) -> list[dict[str, Any]]:
    """Carpetes d'un grup de duplicats per path (folder_stats)."""
    cur = conn.execute(
        """
        SELECT drive_id, folder_path, folder_depth, files_count, total_bytes
        FROM folder_stats WHERE folder_path = ?
        ORDER BY drive_id LIMIT ?
        """,
        (folder_path, limit),
    )
    return [dict(row) for row in cur.fetchall()]


def get_duplicate_folder_by_path_size_entries(
    conn: sqlite3.Connection, folder_path: str, total_bytes: int, limit: int = 50
) -> list[dict[str, Any]]:
    """Carpetes d'un grup de duplicats per path + mida."""
    cur = conn.execute(
        """
        SELECT drive_id, folder_path, folder_depth, files_count, total_bytes
        FROM folder_stats WHERE folder_path = ? AND total_bytes = ?
        ORDER BY drive_id LIMIT ?
        """,
        (folder_path, total_bytes, limit),
    )
    return [dict(row) for row in cur.fetchall()]


EXTENSIONS_LIST_SORT_COLUMNS = ("drive_id", "extension", "count", "total_bytes")


def get_extensions_list(
    conn: sqlite3.Connection,
    drive_ids: list[str] | None,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[dict[str, Any]], int]:
    """Llistat by_extension amb filtre opcional per disc(s). Retorna (rows, total)."""
    if sort_by and sort_by in EXTENSIONS_LIST_SORT_COLUMNS and sort_dir.lower() in ("asc", "desc"):
        order_dir = "ASC" if sort_dir.lower() == "asc" else "DESC"
        order_by = f"{sort_by} {order_dir}, drive_id, count DESC"
    else:
        order_by = "drive_id, count DESC"
    if drive_ids:
        placeholders = ",".join("?" * len(drive_ids))
        cur = conn.execute(
            f"""
            SELECT drive_id, extension, count, total_bytes
            FROM by_extension WHERE drive_id IN ({placeholders}) ORDER BY {order_by} LIMIT ? OFFSET ?
            """,
            (*drive_ids, limit, offset),
        )
        cur_total = conn.execute(
            f"SELECT COUNT(*) FROM by_extension WHERE drive_id IN ({placeholders})",
            drive_ids,
        )
    else:
        cur = conn.execute(
            f"""
            SELECT drive_id, extension, count, total_bytes
            FROM by_extension ORDER BY {order_by} LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        cur_total = conn.execute("SELECT COUNT(*) FROM by_extension")
    rows = [dict(row) for row in cur.fetchall()]
    total = cur_total.fetchone()[0]
    return rows, total


FOLDERS_LIST_SORT_COLUMNS = ("drive_id", "folder_path", "folder_depth", "files_count", "total_bytes")


def get_folders_list(
    conn: sqlite3.Connection,
    drive_ids: list[str] | None,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[dict[str, Any]], int]:
    """Llistat folder_stats amb filtre opcional per disc(s). Retorna (rows, total)."""
    if sort_by and sort_by in FOLDERS_LIST_SORT_COLUMNS and sort_dir.lower() in ("asc", "desc"):
        order_dir = "ASC" if sort_dir.lower() == "asc" else "DESC"
        order_by = f"{sort_by} {order_dir}, drive_id, total_bytes DESC"
    else:
        order_by = "drive_id, total_bytes DESC"
    if drive_ids:
        placeholders = ",".join("?" * len(drive_ids))
        cur = conn.execute(
            f"""
            SELECT drive_id, folder_path, folder_depth, files_count, total_bytes
            FROM folder_stats WHERE drive_id IN ({placeholders}) ORDER BY {order_by} LIMIT ? OFFSET ?
            """,
            (*drive_ids, limit, offset),
        )
        cur_total = conn.execute(
            f"SELECT COUNT(*) FROM folder_stats WHERE drive_id IN ({placeholders})",
            drive_ids,
        )
    else:
        cur = conn.execute(
            f"""
            SELECT drive_id, folder_path, folder_depth, files_count, total_bytes
            FROM folder_stats ORDER BY {order_by} LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        cur_total = conn.execute("SELECT COUNT(*) FROM folder_stats")
    rows = [dict(row) for row in cur.fetchall()]
    total = cur_total.fetchone()[0]
    return rows, total


def get_drive_ids(conn: sqlite3.Connection) -> list[str]:
    """Llista de drive_id per al desplegable de filtres."""
    cur = conn.execute("SELECT DISTINCT drive_id FROM by_extension ORDER BY drive_id")
    return [row[0] for row in cur.fetchall()]


def get_extensions_for_filter(conn: sqlite3.Connection) -> list[str]:
    """Llista d'extensions úniques per al filtre de cerca (by_extension)."""
    cur = conn.execute(
        """
        SELECT DISTINCT extension FROM by_extension
        WHERE extension IS NOT NULL AND extension != ''
        ORDER BY extension
        """
    )
    return [row[0] for row in cur.fetchall()]

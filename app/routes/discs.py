"""GET/POST /discs — Gestió de discs: auditar i incorporar o actualitzar."""
import asyncio
import logging
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import html

from app import queries
from app.audit_to_db import audit_direct_to_db, init_schema
from app.config import database_path

# Longitud màxima del missatge d'error mostrat a la plantilla (evitar HTML massa llarg)
_MAX_ERROR_MSG_LEN = 500


def _sanitize_error_message(msg: str) -> str:
    """Redueix longitud i elimina caràcters que podrien afectar l'HTML."""
    if not msg:
        return "Error desconegut."
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", msg)
    return (s[: _MAX_ERROR_MSG_LEN] + "…") if len(s) > _MAX_ERROR_MSG_LEN else s


def discs_page_get(
    request: Request,
    templates: Jinja2Templates,
    msg_ok: str | None = None,
    msg_error: str | None = None,
) -> HTMLResponse:
    """Pàgina Discs: llista de discs (si hi ha DB) i formulari d'audit."""
    drives: list[dict] = []
    if database_path.is_file():
        try:
            conn = sqlite3.connect(str(database_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            try:
                drives = queries.get_drives_summary(conn)
            finally:
                conn.close()
        except Exception:
            drives = []
    return templates.TemplateResponse(
        "discs.html",
        {
            "request": request,
            "drives": drives,
            "msg_ok": msg_ok,
            "msg_error": msg_error,
        },
    )


def _run_audit_in_thread(
    db_path: Path,
    root_path: Path,
    drive_id: str,
    replace: bool,
    need_init_schema: bool,
) -> tuple[int, int, int]:
    """Executa init_schema (si cal) i audit_direct_to_db en un thread; la connexió es crea i es tanca aquí."""
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        if need_init_schema:
            init_schema(conn)
        return audit_direct_to_db(conn, root_path, drive_id, replace)
    finally:
        conn.close()


def _error_html_response(message: str) -> HTMLResponse:
    """Resposta d'error en HTML sense usar plantilles (evita 500 si Jinja2/url_for falla)."""
    err_escaped = html.escape(message)
    body = (
        "<!DOCTYPE html><html lang='ca'><head><meta charset='UTF-8'><title>Error</title></head><body>"
        "<h1>Error en processar l'auditoria</h1><p class='msg-error'>"
        + err_escaped
        + "</p><p><a href='/discs'>Tornar a Discs</a></p></body></html>"
    )
    return HTMLResponse(content=body, status_code=200)


async def discs_page_post(request: Request, templates: Jinja2Templates) -> HTMLResponse | RedirectResponse:
    """Processa el formulari: auditar carpeta i incorporar/actualitzar a la DB."""
    try:
        form = await request.form()
        root_str = (form.get("root_path") or "").strip()
        drive_id = (form.get("drive_id") or "").strip()
        replace = form.get("replace") in ("on", "true", "1")

        if not drive_id:
            return _error_html_response("Cal indicar l'identificador del disc (drive_id).")

        root_path: Path | None = None
        if root_str:
            try:
                root_path = Path(root_str).resolve()
            except Exception:
                pass
        if not root_path or not root_path.is_dir():
            return _error_html_response(
                "La ruta de la carpeta o disc a auditar no existeix o no és un directori."
            )

        need_init = not database_path.is_file()
        if need_init:
            database_path.parent.mkdir(parents=True, exist_ok=True)
        inv_count, folder_count, ext_count = await asyncio.to_thread(
            _run_audit_in_thread,
            database_path,
            root_path,
            drive_id,
            replace,
            need_init,
        )

        msg = f"Importats: {inv_count} fitxers, {folder_count} carpetes, {ext_count} extensions."
        return RedirectResponse(url=f"/discs?ok={quote(msg)}", status_code=302)
    except Exception as e:
        logging.exception("Error en POST /discs (auditoria)")
        err_msg = _sanitize_error_message(str(e))
        return _error_html_response(err_msg)


async def discs_delete_post(request: Request) -> RedirectResponse:
    """Elimina una unitat (drive_id) de la base de dades i redirigeix a /discs."""
    try:
        form = await request.form()
        drive_id = (form.get("drive_id") or "").strip()
        if not drive_id:
            return RedirectResponse(
                url="/discs?error=" + quote("Cal indicar l'identificador del disc (drive_id)."),
                status_code=302,
            )
        if not database_path.is_file():
            return RedirectResponse(
                url="/discs?error=" + quote("No hi ha base de dades."),
                status_code=302,
            )
        conn = sqlite3.connect(str(database_path), timeout=10.0)
        try:
            conn.execute("DELETE FROM inventory WHERE drive_id = ?", (drive_id,))
            conn.execute("DELETE FROM folder_stats WHERE drive_id = ?", (drive_id,))
            conn.execute("DELETE FROM by_extension WHERE drive_id = ?", (drive_id,))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse(
            url=f"/discs?ok={quote('Unitat «' + drive_id + '» eliminada de la base de dades.')}",
            status_code=302,
        )
    except Exception as e:
        logging.exception("Error en POST /discs/delete")
        return RedirectResponse(
            url="/discs?error=" + quote(_sanitize_error_message(str(e))),
            status_code=302,
        )

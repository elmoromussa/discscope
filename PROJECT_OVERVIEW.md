# DiscScope — Visió general del projecte

Document de referència per recuperar el context del projecte en futurs xats.

## Estructura del projecte

```
DiscScope/
├── app/
│   ├── __init__.py
│   ├── main.py           # Entrada FastAPI, rutes, Jinja2
│   ├── config.py         # database_path (DATABASE_PATH o data/arxiu_discs.db)
│   ├── db.py             # get_db() — connexió SQLite per petició
│   ├── queries.py        # Consultes SQL (dashboard, cerca, duplicats, extensions, folders)
│   ├── queries_explorer.py # Consultes per a l'explorador simulat (arbre i contingut des de inventory)
│   ├── audit_to_db.py    # Esquema + audit directe a DB (sense CSV intermedis)
│   ├── routes/
│   │   ├── dashboard.py, search.py, duplicates.py, extensions.py, folders.py, explorer.py, discs.py
│   │   └── ...
│   ├── templates/       # Jinja2 (base.html, dashboard, search, discs, welcome, ...)
│   └── static/           # style.css, app.js
├── data/                 # Ubicació de arxiu_discs.db (exclosa per .gitignore)
├── .gitignore             # Exclou data/, venv/, *.db, .env
├── README.md
├── requirements.txt
└── run_inventari_WIN.bat
```

La carpeta **temp/** no forma part del projecte; conté scripts històrics (quick_audit_archive, import_audit_to_db, .bat) que s’han integrat o substituït per el flux directe a la DB des de la GUI.

## Stack

- **Backend:** Python 3.10+, FastAPI, uvicorn
- **Plantilles:** Jinja2 (FastAPI Jinja2Templates)
- **Base de dades:** SQLite3 (stdlib), lectura des de l’app; escriptura només des de la gestió de discs (audit directe o import CSV)
- **Frontend:** HTML + CSS + JS mínim (tema clar/fosc)

## Base de dades

- **Ruta:** `app/config.py` — per defecte `PROJECT_ROOT / "data" / "arxiu_discs.db"`; override amb variable d’entorn `DATABASE_PATH`.
- **Esquema** (taules llegides/escrites per l’app):

  - **inventory**: id, drive_id, relative_path, name, extension, size_bytes, modified_utc. Índexs: drive_id, (drive_id, extension), name.
  - **folder_stats**: id, drive_id, folder_path, folder_name, folder_depth, files_count, total_bytes. Índexs: drive_id, folder_name.
  - **by_extension**: id, drive_id, extension, count, total_bytes. Índex: drive_id.

- **Creació/actualització:** via `app/audit_to_db.py`: `init_schema(conn)` i `audit_direct_to_db(conn, root_path, drive_id, replace)`. Flux principal: auditar una carpeta arrel i escriure directament a la DB (un disc cada vegada, sense CSV intermedis). Opcional: import des de carpeta d’audit existent (CSV).

## Flux de dades

- **Històric:** Els scripts de temp generaven CSV (quick_audit_archive) i després s’importaven a la DB (import_audit_to_db). En el projecte integrat, el flux és **auditar i escriure directament a la DB** des de la pàgina “Discs”.
- **Discs grans (5–8 TB, molts fitxers):** L’audit directe usa memòria fitada: `os.walk` + buffer de N fitxers (chunk), `executemany` a `inventory`, i diccionaris per `folder_stats` i `by_extension` (inserits en batch al final). Una sola transacció per disc.

## Rutes

| Ruta | Descripció |
|------|-------------|
| `/` | Inici: si no hi ha DB → benvinguda; si hi ha DB → dashboard (resum per disc, top extensions, top carpetes) |
| `/search` | Cerca per paraula clau (nom/ruta), filtres per disc |
| `/duplicates` | Duplicats per nom o nom+mida (fitxers/carpetes) |
| `/extensions` | Llistat per extensió (paginat) |
| `/folders` | Llistat de carpetes per mida (paginat) |
| `/explorador` | Explorador simulat d'arxius i carpetes des de la DB (arbre col·lapsable + contingut; sense accés al sistema de fitxers) |
| `/discs` | Gestió de discs: auditar i incorporar, o actualitzar un disc (formulari; missatges via query params) |
| `/health` | JSON: database_exists, database_path |

## Mòduls clau

- **app/main.py:** App FastAPI, muntatge de rutes i plantilles, filtre `format_bytes`.
- **app/config.py:** `database_path` (DATABASE_PATH o default).
- **app/db.py:** `get_db()` — obre SQLite; si el fitxer no existeix, retorna 503.
- **app/queries.py:** Totes les consultes de lectura (dashboard, cerca, duplicats, extensions, folders, get_drive_ids, etc.).
- **app/queries_explorer.py:** Consultes per a l'explorador (get_explorer_drive_ids, get_explorer_children, get_explorer_contents); deriva l'arbre des de `inventory.relative_path`.
- **app/audit_to_db.py:** `init_schema`, `audit_direct_to_db` (walk + inserció en chunks), opcional `import_from_csv_folder`.
- **app/routes/explorer.py:** Pàgina Explorador (GET /explorador; requereix DB).
- **app/routes/discs.py:** Pàgina Discs (GET sense DB opcional per llista; POST audit directe o import CSV).

## Comportament sense DB

- **`/`:** Si `database_path` no és un fitxer, es renderitza la pàgina de benvinguda (enllaç a “Discs” per crear la primera DB).
- **`/discs`:** Es carrega sense dependre de `get_db` per al GET; es mostra el formulari d’audit (i opcionalment import CSV). En POST es pot crear la DB (init_schema) i executar l’audit directe.
- **Altres rutes** (search, duplicates, extensions, folders, explorador): depenen de `get_db()`; si no hi ha DB, retornen 503.

## Idioma

Missatges i etiquetes de la GUI en **català**.

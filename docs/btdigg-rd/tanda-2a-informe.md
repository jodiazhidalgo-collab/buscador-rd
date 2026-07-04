# TANDA 2A - Informe final

## Resumen

TANDA 2A ejecutada como extraccion interna conservadora. No se han cambiado rutas HTTP visibles, nombres de endpoint, payloads publicos, `data/`, runtime del motor ni `rd_turbo_pro.py`.

## Archivos creados

- `docs/btdigg-rd/tanda-2a-plan.md`
- `docs/btdigg-rd/tanda-2a-informe.md`
- `app/api/btdigg_rd/_runtime_dirs.py`
- `app/api/btdigg_rd/_job_artifacts.py`
- `app/api/btdigg_rd/_send_tracking.py`
- `app/api/btdigg_rd/_qbt_client.py`
- `app/api/btdigg_rd/_rd_client.py`
- `app/api/btdigg_rd/_rdt_client.py`
- `app/api/btdigg_rd/_settings_service.py`
- `app/api/btdigg_rd/_tv_rules_service.py`
- `app/api/btdigg_rd/_ui_state_service.py`
- `tests/test_routes_contract.py`
- `tests/test_jobs_contract.py`
- `tests/test_send_contract.py`
- `tests/test_settings_contract.py`

## Archivos modificados

- `app/api/btdigg_rd/jobs.py`
- `app/api/btdigg_rd/send.py`
- `app/api/btdigg_rd/routes.py`
- `tests/conftest.py`

## Logica extraida

- `jobs.py`: runtime de job, `RunScope`, `JobRuntime`, creacion de rutas runtime, `cancel.json` y promocion de artefactos a `config/btdigg-rd/data/motor/exports`.
- `send.py`: tracking de descarga, helpers de texto/enlace, cliente qBittorrent, cliente Real-Debrid basico y helpers puros de RDT native.
- `routes.py`: settings, qbit-toggle, reglas TV y UI state a servicios internos pequenos.

## Wrappers conservados

- `jobs.py` mantiene `RunScope`, `JobRuntime`, `create_job_runtime`, `_write_cancel_file`, `_cancel_doc` y `_promote_successful_artifacts`.
- `send.py` mantiene `api_rdt_send`, `rd_token`, `rd_api`, `qbit_add_url`, `qbit_add_torrent_bytes`, `client_info_by_hash`, `rdt_native_*` y rutas legacy/nativas como nombres importables.
- `routes.py` mantiene los mismos nombres de endpoints Flask y las mismas URL publicas.

## No tocado

- `app/motor/btdigg/rd_turbo_pro.py`
- `data/`
- `config/btdigg-rd/data/motor/config.json`
- `config/btdigg-rd/data/motor/rd_token.txt`
- `config/btdigg-rd/data/motor/exports/`
- UI y assets frontend
- Dockerfile y compose

## Pruebas ejecutadas

- `python -m pytest -q`: 36 passed
- `python -m unittest discover -s tests -v`: 22 tests OK
- `python -m compileall -q app tests`: OK
- Rebuild Docker `btdigg-rd`: OK
- Smoke HTTP vivo:
  - `GET /api/job/active`: OK
  - `GET /api/qbit-toggle`: OK
  - `GET /api/settings`: OK

## Riesgos pendientes para TANDA 3

- `rd_turbo_pro.py` sigue siendo el monolito principal y no se ha partido.
- La parte RDT native de `send.py` aun mezcla cliente y flujo de decision; queda preparada para extraer mas, pero no conviene forzarlo sin mas tests.
- Nota actual: el runtime del motor fue migrado a `config/btdigg-rd/data/motor/` en una tanda posterior.
- El proximo zip de handoff debe excluir `_codex_runtime/`, `.git/`, `_backups/`, handoffs, capturas y secretos runtime.

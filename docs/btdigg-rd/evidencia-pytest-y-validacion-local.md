# Evidencia pytest y validacion local

## Motivo

Este archivo existe para que cualquier revision externa del ZIP vea claramente que el proyecto ya trae base pytest y que la suite se ejecuto en el entorno real de BTDigg + RD.

Si una sandbox externa dice que no puede ejecutar pytest/unittest por falta de Flask, pytest o red, eso describe una limitacion de esa sandbox. No significa que el proyecto no tenga pytest preparado.

## Archivos que prueban que pytest esta integrado

- `requirements-dev.txt`
  - Incluye `-r requirements.txt`.
  - Incluye `pytest>=8.4,<9`.
- `pytest.ini`
  - `minversion = 8.4`.
  - `testpaths = tests`.
  - `python_files = test_*.py`.
  - `addopts = -ra`.
- `tests/conftest.py`
  - Mete `app/` en `sys.path`.
  - Fija `DATA_DIR` seguro en `_codex_runtime/test-data/pytest-session`.
  - Expone fixtures `app`, `client`, `runner`.
  - Expone `isolated_data_dir` con `tmp_path` y `monkeypatch`.
  - Recarga modulos sensibles a `DATA_DIR`.

## Tests pytest visibles en el ZIP

- `tests/test_pytest_contracts.py`
- `tests/test_routes_contract.py`
- `tests/test_jobs_contract.py`
- `tests/test_send_contract.py`
- `tests/test_settings_contract.py`
- `tests/test_text_encoding_contract.py`
- `tests/test_motor_characterization.py`
- `tests/test_motor_retry_contract.py`
- `tests/test_motor_qbt_probe_contract.py`
- `tests/test_motor_exports_contract.py`
- `tests/test_motor_prepare_contract.py`
- `tests/test_motor_rd_availability_contract.py`

Tambien conviven tests antiguos basados en `unittest`, por ejemplo:

- `tests/test_job_cancel.py`
- `tests/test_motor_cancel.py`
- `tests/test_title_resolver_api.py`
- `tests/test_title_resolver_parser.py`
- `tests/test_title_resolver_service.py`

## Comandos para reproducir desde cero

Desde la raiz del proyecto:

```powershell
python -m pip install -r requirements-dev.txt
python -m compileall -q app tests
python -m pytest -q
python -m unittest discover -s tests -v
```

Si la sandbox externa no tiene red y no tiene dependencias instaladas, puede leer la configuracion anterior, pero no podra ejecutar la suite completa hasta instalar `requirements-dev.txt`.

## Evidencia del entorno real local

Fecha de verificacion local: 2026-07-01.

```text
python --version
Python 3.14.2

python -m pytest --version
pytest 8.4.2

python -m pip show pytest Flask
Name: pytest
Version: 8.4.2
Location: C:\Users\lacab\AppData\Roaming\Python\Python314\site-packages

Name: Flask
Version: 3.0.3
Location: C:\Users\lacab\AppData\Roaming\Python\Python314\site-packages
```

## Resultado de validacion local

Ejecucion realizada en el entorno real del proyecto:

```text
python -m compileall -q app tests
OK

python -m pytest -q
................................................................         [100%]
64 passed in 6.01s

python -m unittest discover -s tests -v
Ran 22 tests in 2.259s
OK
```

## Auditoria Tanda 4 final

Fecha de auditoria local: 2026-07-01.

Backup previo creado:

```text
_backups/20260701-122453-tanda-4-auditoria-final.zip
```

Delta aplicado:

```text
No se aplico refactor nuevo.
La tanda final ya existia y los gates del motor pasaron.
Solo se actualizo esta evidencia final.
```

Comandos ejecutados y resultado:

```text
git status --short
OK: limpio antes de empezar.

python -m compileall -q app tests
OK

python -m pytest -q tests/test_motor_retry_contract.py tests/test_motor_qbt_probe_contract.py tests/test_motor_exports_contract.py tests/test_motor_prepare_contract.py tests/test_motor_rd_availability_contract.py tests/test_motor_characterization.py tests/test_text_encoding_contract.py
22 passed in 2.61s

python -m pip install -r requirements-dev.txt
OK: dependencias ya satisfechas, incluyendo Flask 3.0.3 y pytest 8.4.2.

python -m compileall -q app tests
OK

python -m pytest -q
64 passed in 6.63s

python -m unittest discover -s tests -v
Ran 22 tests in 2.263s
OK

powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\rebuild-btdigg-rd\scripts\rebuild_and_check.ps1
OK: contenedor btdigg-rd levantado y HTTP 200.
```

Smokes HTTP minimos:

```text
GET /api/job/active -> 200
GET /api/settings -> 200
GET /api/qbit-toggle -> 200
POST /api/rdt/send sin link -> 400 esperado
POST /api/job con modulo invalido -> 400 esperado
```

Comprobaciones de auditoria:

```text
Wrappers del motor conservados:
- rd_call_with_retry
- qbt_probe_one
- export_results
- rd_check_availability
- prepare_results

Extracciones existentes confirmadas:
- app/motor/btdigg/_motor_rd_retry.py
- app/motor/btdigg/_motor_qbt_probe.py
- app/motor/btdigg/_motor_exports.py

Zonas congeladas intencionalmente:
- browser_collect_page
- browser_download_controls
- rd_verify_by_addmagnet
- rd_verify_addmagnet_queue
- salida completa de prepare_results a modulo nuevo
- salida completa de rd_check_availability a modulo nuevo

Runtime real no trackeado ni movido:
- data/
- config/btdigg-rd/data/motor/config.json
- config/btdigg-rd/data/motor/rd_token.txt
- config/btdigg-rd/data/motor/exports/
- app/motor/btdigg/temp/
```

## Interpretacion correcta para revisiones externas

- El proyecto si trae pytest integrado.
- Pytest no se incluye como binario dentro del ZIP; se declara en `requirements-dev.txt`.
- La suite pytest y la suite unittest conviven.
- Los tests no deben tocar `data/` real; usan `_codex_runtime/` y `tmp_path`.
- Si una sandbox externa no instala dependencias, su limitacion debe quedar anotada como limitacion de entorno, no como defecto del repo.

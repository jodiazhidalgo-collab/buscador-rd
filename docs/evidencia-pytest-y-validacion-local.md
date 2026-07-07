# Evidencia pytest y validacion local

## Motivo

Este archivo existe para que cualquier revision externa vea claramente que Buscador RD trae base pytest desde la raiz del proyecto unificado, con contratos propios para motor, RD/qB, jobs, voz, caja negra y rutas publicas.

Si una sandbox externa no instala dependencias o no puede ejecutar pytest, eso describe una limitacion de esa sandbox. No significa que el proyecto no tenga pytest preparado.

## Archivos que prueban que pytest esta integrado

- `.github/workflows/ci.yml`
  - Ejecuta pytest en GitHub Actions con Python 3.12.
  - Genera `buscador-rd-pytest-junit.xml` como evidencia descargable.
  - Publica el artefacto `buscador-rd-pytest-evidence`.
  - Es ejecutable automaticamente en `push`/`pull_request` y manualmente con `workflow_dispatch`.
- `pytest.ini`
  - `minversion = 8.4`.
  - `testpaths` apunta a `services/btdigg-rd/tests`.
  - `python_files = test_*.py`.
  - `addopts = -ra`.
  - Declara el marcador `live` para pruebas reales controladas.
- `services/btdigg-rd/requirements-dev.txt`
  - Incluye `pytest>=8.4,<9`.
  - Reusa las dependencias reales del servicio con `-r requirements.txt`.
- `services/btdigg-rd/tests/conftest.py`
  - Fija rutas seguras bajo `_codex_runtime/test-data/pytest-session`.
  - Expone fixtures aisladas para Flask, jobs y modulos sensibles a `DATA_DIR`.
  - Evita que las pruebas sinteticas toquen `config/btdigg-rd/data`.

## Tests pytest visibles en el repo

- `services/btdigg-rd/tests/test_project_governance.py`
- `services/btdigg-rd/tests/test_pytest_contracts.py`
- `services/btdigg-rd/tests/test_blackbox_sequence_contract.py`
- `services/btdigg-rd/tests/test_jobs_contract.py`
- `services/btdigg-rd/tests/test_send_contract.py`
- `services/btdigg-rd/tests/test_search_queue_contract.py`
- `services/btdigg-rd/tests/test_settings_contract.py`
- `services/btdigg-rd/tests/test_routes_contract.py`
- `services/btdigg-rd/tests/test_voice_diagnostics_contract.py`
- `services/btdigg-rd/tests/test_voice_transcription.py`
- `services/btdigg-rd/tests/test_title_resolver_service.py`
- `services/btdigg-rd/tests/test_spoken_title_resolver.py`
- `services/btdigg-rd/tests/test_motor_*.py`
- `services/btdigg-rd/tests/test_live_search_web.py`

## Comandos para reproducir desde cero

Desde la raiz del proyecto:

```powershell
python -m venv _codex_runtime\tmp\venv_buscador_rd_pytest
.\_codex_runtime\tmp\venv_buscador_rd_pytest\Scripts\python.exe -m pip install --upgrade pip
.\_codex_runtime\tmp\venv_buscador_rd_pytest\Scripts\python.exe -m pip install -r services\btdigg-rd\requirements-dev.txt
.\_codex_runtime\tmp\venv_buscador_rd_pytest\Scripts\python.exe -m compileall -q services\btdigg-rd services\cloudflared
.\_codex_runtime\tmp\venv_buscador_rd_pytest\Scripts\python.exe -m pytest -q --junitxml _codex_runtime\artifacts\buscador-rd-pytest-junit.xml --durations=20
```

Los tests live de busqueda web real siguen protegidos por `BTDIGG_LIVE=1` y no se fuerzan en la suite segura.

## Evidencia del entorno real local

Fecha de verificacion local: 2026-07-07.

```text
python --version
Python 3.14.2

python -m pytest --version
pytest 8.4.2
```

## Resultado de validacion local

Ejecucion realizada desde la raiz del proyecto:

```text
python -m pytest --collect-only -q
134 tests collected in 2.43s

python -m compileall -q services\btdigg-rd services\cloudflared
OK

python -m pytest -q --junitxml _codex_runtime\artifacts\buscador-rd-pytest-junit.xml --durations=20
132 passed, 2 skipped in 13.15s
```

El informe JUnit generado localmente contiene:

```text
Tests: 134
Failures: 0
Errors: 0
Skipped: 2
```

## Interpretacion correcta para revisiones externas

- Buscador RD si trae pytest integrado desde la raiz.
- Pytest no se incluye como binario dentro del repo; se declara en `services/btdigg-rd/requirements-dev.txt`.
- GitHub Actions guarda un informe JUnit y lo publica como artefacto `buscador-rd-pytest-evidence`.
- La suite pytest raiz ejecuta contratos propios de Buscador RD y los tests del servicio principal.
- Los tests sinteticos usan `_codex_runtime/test-data/pytest-session` o `tmp_path`.
- Los tests live quedan saltados salvo que se active una variable explicita.
- Si una sandbox externa no instala dependencias, su limitacion debe quedar anotada como limitacion de entorno, no como defecto del repo.

# TANDA FINAL - Informe final

## Resumen

TANDA FINAL ejecutada de forma conservadora. Se redujo el riesgo del monolito `app/motor/btdigg/rd_turbo_pro.py` sin mover runtime real, sin cambiar rutas HTTP, sin cambiar nombres Flask y sin cambiar claves JSON publicas.

La tanda se cerro aplicando el camino preferido para las piezas de bajo-medio riesgo y el camino de contingencia para las zonas acopladas:

- Extraidas completas con wrapper: `rd_call_with_retry`, `qbt_probe_one`, `export_results`.
- Troceadas dentro del mismo archivo: `rd_check_availability`, `prepare_results`.
- Congeladas intencionalmente: scraping/navegador/addMagnet profundo.

## Backup previo

- `_backups/20260701-111948-tanda-final-motor.zip`

## Base y rollback

- Base previa: `ce4a4e5 fix: clean residual mojibake`.
- Rollback exacto si hiciera falta: volver a la base `ce4a4e5` o restaurar el ZIP `_backups/20260701-111948-tanda-final-motor.zip`.
- Si solo fallara una extraccion, revertir el bloque de esa extraccion y conservar tests/documentacion que sigan verdes.

## Archivos creados

- `docs/tanda-final-plan.md`
- `docs/tanda-final-informe.md`
- `app/motor/btdigg/_motor_rd_retry.py`
- `app/motor/btdigg/_motor_qbt_probe.py`
- `app/motor/btdigg/_motor_exports.py`
- `tests/test_motor_retry_contract.py`
- `tests/test_motor_qbt_probe_contract.py`
- `tests/test_motor_exports_contract.py`
- `tests/test_motor_prepare_contract.py`
- `tests/test_motor_rd_availability_contract.py`

## Archivos modificados

- `app/motor/btdigg/rd_turbo_pro.py`
- `tests/test_text_encoding_contract.py`

## Wrappers conservados

Siguen existiendo en `rd_turbo_pro.py` con los mismos nombres publicos:

- `rd_call_with_retry`
- `qbt_probe_one`
- `export_results`
- `rd_check_availability`
- `prepare_results`

## Funciones extraidas

- `rd_call_with_retry` delega en `app/motor/btdigg/_motor_rd_retry.py`.
- `qbt_probe_one` delega en `app/motor/btdigg/_motor_qbt_probe.py`.
- `export_results` delega en `app/motor/btdigg/_motor_exports.py`.

Las dependencias se pasan desde el wrapper: `CONFIG`, `diag`, `log`, `cancel_checkpoint`, `sleep_interruptible`, `rd_api`, `RDAPIError`, helpers de qB y paths de export.

## Funciones troceadas dentro del motor

- `rd_check_availability`
  - Nuevo helper interno: `_rd_verify_batch_when_instant_api_off`.
  - Reduce duplicacion de la rama addMagnet cuando `instantAvailability` esta desactivado o cacheado como desactivado.
- `prepare_results`
  - Nuevo helper interno: `_prepare_query_prefilter`.
  - Aisla la criba por query/rescate/descartes sin cambiar el flujo externo.

No se movieron a modulo nuevo porque siguen dependiendo de muchas piezas globales del motor y forzar esa salida aumentaba riesgo.

## Congelado por seguridad

Estas zonas quedan intencionalmente congeladas:

- `browser_collect_page`
- `browser_download_controls`
- `rd_verify_by_addmagnet`
- `rd_verify_addmagnet_queue`
- Extraccion completa de `prepare_results`
- Extraccion completa de `rd_check_availability`

Motivo: scraping, navegador y addMagnet tienen alto acoplamiento con red, runtime RD y estado del motor. Se mantienen cubiertas indirectamente por contratos y se dejan sin reforma agresiva.

## Tests anadidos

- `tests/test_motor_retry_contract.py`
  - Reintento 429.
  - Reintento temporal.
  - Error terminal/infringing sin reintento.
  - Refresh de slots en limite 21.
  - Propagacion de la ultima excepcion agotada.
- `tests/test_motor_qbt_probe_contract.py`
  - Sin hash/magnet.
  - Ya existia en qBittorrent.
  - Add OK + poll OK.
  - Add error.
  - Cancelacion con borrado del probe.
- `tests/test_motor_exports_contract.py`
  - `ULTIMOS_RESULTADOS.json`.
  - `ULTIMO_TOP.txt`.
  - `ULTIMO_QBIT_VIVOS.txt`.
  - `ULTIMO_RD_TEMPORAL.txt`.
  - Campos esperados y escritura UTF-8.
- `tests/test_motor_prepare_contract.py`
  - Scoring, filtro por score, orden antes de RD, qbit extras y export final.
  - Filtro por tamano antes y despues de RD.
  - Rescate RD de candidatos dudosos cuando corresponde.
- `tests/test_motor_rd_availability_contract.py`
  - Token ausente.
  - `instantAvailability` cacheado como desactivado.
  - Rama endpoint desactivado con addMagnet batch.
  - Resumen final recalculado.
- `tests/test_text_encoding_contract.py`
  - Guardarrail ampliado a los modulos nuevos del motor.

## Resultados de pruebas

- `python -m compileall -q app tests`: OK.
- `python -m pytest -q`: 64 passed.
- `python -m unittest discover -s tests -v`: 22 tests OK.
- Auditoria encoding/BOM/LF en archivos tocados: OK, sin `\u00c3`, sin `\u00c2`, sin BOM, sin CRLF.

## Rebuild y smokes

- Rebuild `btdigg-rd`: OK.
- Contenedor `btdigg-rd`: levantado.
- HTTP `9007`: 200.

Smokes HTTP:

- `GET /api/job/active`: 200 OK.
- `GET /api/settings`: 200 OK.
- `GET /api/qbit-toggle`: 200 OK.
- `POST /api/rdt/send` sin link: 400 esperado.
- `POST /api/job` con modulo invalido: 400 esperado.

Mapa de rutas clave comprobado con `create_app()`:

- `/api/job`: POST.
- `/api/rdt/send`: POST.
- `/api/settings`: POST.
- `/api/qbit-toggle`: POST.
- `/api/tv-rules`: POST.
- `/api/title-resolver/resolve`: POST.
- `/api/results/<module>`: GET.
- `/api/history/btdigg`: GET.

Blackbox posterior final:

- Ultimo diagnostico: `data/diagnostics/btdigg/downloads/2026-07-01/5a8d503833`.
- Estado: `rejected`.
- Motivo: `sin enlace`, generado por el smoke esperado de `/api/rdt/send`.
- No indica fallo real del motor.

## Runtime y contratos

No se movio ni modifico:

- `data/`
- `app/motor/btdigg/config.json`
- `app/motor/btdigg/rd_token.txt`
- `app/motor/btdigg/exports/`
- rutas HTTP publicas
- nombres de endpoint Flask
- claves JSON publicas
- frontend funcional

## Tamano del motor

- Antes aproximado: 6099 lineas.
- Despues: 5892 lineas en `rd_turbo_pro.py`.
- Nuevos modulos:
  - `_motor_rd_retry.py`: 156 lineas.
  - `_motor_qbt_probe.py`: 114 lineas.
  - `_motor_exports.py`: 133 lineas.

## Commit

- Pendiente de cierre Git local al final de esta tanda. El hash exacto queda en la respuesta final y en `git log`.

## Criterio de cierre

La tanda puede considerarse cierre conservador porque:

- La matriz completa queda verde.
- Los wrappers publicos siguen existiendo.
- Las piezas de bajo-medio riesgo salieron del monolito.
- Las piezas acopladas se trocearon sin forzar circular imports.
- Las zonas peligrosas de scraping/navegador/addMagnet quedaron congeladas a proposito.
- El runtime real queda intacto.
- El servicio reconstruye y responde en `9007`.

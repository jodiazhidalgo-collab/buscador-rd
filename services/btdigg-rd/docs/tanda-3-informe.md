# TANDA 3 - Informe final

## Que se corrigio

- Se corrigio mojibake en `routes.py`, `send.py`, `_settings_service.py` y `_qbt_client.py`.
- Los archivos tocados quedaron en UTF-8 sin BOM y LF.
- Se anadio guardarrail automatico para fallar si vuelven a aparecer marcadores `\u00c3` o `\u00c2` en archivos tocados.
- Se actualizaron contratos publicos criticos para exigir `módulo no válido`, labels de settings con acentos correctos y respuestas de `/api/job` y `/api/results/<module>` con modulo invalido.

## Que se extrajo

- `app/api/btdigg_rd/_send_contracts.py`
  - validacion de tarjeta BTDigg actual e historial,
  - construccion de contrato de descarga,
  - decision de ruta `RD_REUSABLE`, `RD_VERIFIED_MAGNET`, `QBIT_REUSABLE` y bloqueos,
  - trazado de resumen de contrato.
- `app/api/btdigg_rd/_send_routing.py`
  - resolucion de destino movies/tv/manual,
  - wrappers de clasificacion de titulo,
  - construccion de rutas de destino para RDT/qB.
- `app/api/btdigg_rd/_send_manual_flow.py`
  - flujo manual magnet RD-first con fallback a qBittorrent,
  - flujo manual URL/.torrent RD-first con fallback a qBittorrent.

`app/api/btdigg_rd/send.py` queda como fachada compatible y sigue exportando los nombres usados por el proyecto mediante imports/wrappers.

## Que quedo cubierto por tests

- Cadenas publicas sin mojibake.
- `/api/job` con modulo invalido.
- `/api/results/<module>` con modulo invalido.
- `/api/rdt/send` sin link.
- `/api/rdt/send` manual magnet con fallback a qBittorrent.
- Decision de ruta `RD_REUSABLE`, `RD_VERIFIED_MAGNET`, `QBIT_REUSABLE` y `BLOCKED_*`.
- Wrappers importables de `send.py` hacia modulos nuevos.
- Contrato de construccion de descarga BTDigg.
- Caracterizacion minima del motor sin red real.

## Que NO se toco

- No se modifico `app/motor/btdigg/rd_turbo_pro.py`.
- No se movio `data/`.
- No se movio `app/motor/btdigg/config.json`.
- No se movio `app/motor/btdigg/rd_token.txt`.
- No se movio `app/motor/btdigg/exports/`.
- No se tocaron rutas HTTP publicas, nombres de endpoint Flask ni claves JSON publicas.
- No se toco frontend.

## Preparacion TANDA 4

Funciones candidatas localizadas en `app/motor/btdigg/rd_turbo_pro.py`:

- `rd_call_with_retry`: linea 1588.
- `qbt_probe_one`: linea 1790.
- `export_results`: linea 3838.
- `rd_check_availability`: linea 5077.
- `prepare_results`: linea 5241.

Estas zonas no se han movido en TANDA 3. La recomendacion es partirlas en TANDA 4 solo despues de ampliar caracterizacion alrededor de escrituras de exports, llamadas RD, probe qB y filtrado/preparacion de resultados.

## Riesgos abiertos

- `rd_turbo_pro.py` sigue siendo monolitico, 6099 lineas. El mojibake residual detectado en auditoria posterior se corrigio como cambio de texto no funcional.
- `send.py` ya bajo a 1292 lineas, pero aun contiene flujo RDT native y rutas RD reutilizable dentro de la fachada. Es el siguiente punto razonable antes de partir motor.
- Los smokes HTTP finales dependen de que el servicio local/NAS este disponible tras rebuild.

## Resultados parciales de fase

- T3-A: `python -m compileall -q app tests` OK.
- T3-A: `python -m pytest -q tests/test_text_encoding_contract.py tests/test_settings_contract.py tests/test_routes_contract.py tests/test_send_contract.py` -> 10 passed.
- T3-B: `python -m pytest -q tests/test_send_contract.py tests/test_text_encoding_contract.py tests/test_routes_contract.py tests/test_settings_contract.py` -> 16 passed.
- T3-C: `python -m pytest -q tests/test_motor_characterization.py` -> 3 passed.

## Resultados finales

- `python -m compileall -q app tests` OK.
- `python -m pytest -q` -> 47 passed.
- `python -m unittest discover -s tests -v` -> 22 tests OK.
- Auditoria posterior: se corrigio `tests/test_job_cancel.py` para usar `_codex_runtime/test-data/test_job_cancel_<pid>` y evitar falsos fallos si dos runners se ejecutan a la vez.
- Rebuild `btdigg-rd` OK, contenedor levantado y HTTP 200 en puerto 9007.
- Smokes HTTP OK:
  - `GET /api/job/active` -> 200.
  - `GET /api/settings` -> 200.
  - `GET /api/qbit-toggle` -> 200.
  - `POST /api/rdt/send` sin link -> 400 esperado.
  - `POST /api/settings` con modulo invalido -> 400 esperado.

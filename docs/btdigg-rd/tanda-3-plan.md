# TANDA 3 - Plan conservador

## Objetivo

Cerrar defectos residuales de TANDA 2A, reducir riesgo interno en `send.py` y preparar la futura TANDA 4 sobre `rd_turbo_pro.py` sin cambiar contratos publicos ni mover runtime real.

## Alcance

- Corregir mojibake y normalizar a UTF-8 sin BOM y LF en archivos tocados por T3-A.
- Anadir guardarrailes de test para cadenas publicas criticas sin mojibake.
- Extraer piezas internas de `send.py` a modulos pequenos del mismo paquete, manteniendo `send.py` como fachada compatible.
- Caracterizar el motor con pruebas observables sin red real y documentar zonas candidatas de TANDA 4.
- Mantener intactos endpoints, nombres Flask, payloads JSON y `data/` salvo tanda propia.

## Archivos previstos

- `app/api/btdigg_rd/routes.py`
- `app/api/btdigg_rd/send.py`
- `app/api/btdigg_rd/_settings_service.py`
- `app/api/btdigg_rd/_qbt_client.py`
- `app/api/btdigg_rd/_send_contracts.py`
- `app/api/btdigg_rd/_send_routing.py`
- `tests/test_text_encoding_contract.py`
- `tests/test_send_contract.py`
- `tests/test_routes_contract.py`
- `tests/test_motor_characterization.py`
- `docs/btdigg-rd/tanda-3-informe.md`

## Riesgos

- `send.py` sigue mezclando endpoint HTTP, decisiones RD/qB, flujo manual, RDT native y respuestas JSON. Las extracciones deben ser mecanicas y con wrappers importables.
- Los textos mojibake pueden estar cubiertos por tests antiguos que congelaron el texto roto; esos tests deben pasar a exigir acentos correctos sin cambiar contrato.
- `rd_turbo_pro.py` es monolitico y acoplado a runtime real. En esta tanda solo se caracteriza y documenta; partirlo queda fuera de alcance.
- Cualquier cambio en rutas HTTP, nombres de endpoints o claves JSON visibles es regresion y debe parar la tanda.

## Base y rollback

- Base Git limpia antes de empezar: `211237c`.
- Backup previo: `_backups/20260701-103428-tanda-3-conservadora.zip`.
- Si falla la matriz de pruebas, cambia un contrato publico, hace falta mover runtime real o tocar `rd_turbo_pro.py` de forma no trivial, se para la tanda y se vuelve a la base `211237c` o al backup indicado.

## Criterio de salida

- `python -m compileall -q app tests` OK.
- `python -m pytest -q` OK.
- `python -m unittest discover -s tests -v` OK.
- Smokes HTTP basicos OK si el entorno local lo permite.
- `git diff` acotado a documentacion, tests, correcciones de codificacion y extracciones internas compatibles.

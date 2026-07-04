# TANDA FINAL - Plan conservador

## Objetivo

Cerrar el saneo interno de BTDigg + RD reduciendo el riesgo principal pendiente en `app/motor/btdigg/rd_turbo_pro.py`, sin cambiar contratos publicos, runtime real ni comportamiento externo.

## Alcance

- Blindar con tests observables las zonas del motor indicadas antes de extraer.
- Extraer de forma conservadora funciones de bajo-medio riesgo con wrappers compatibles en `rd_turbo_pro.py`.
- Trocear dentro del propio motor las zonas que no sean seguras de sacar a modulo sin forzar circular imports.
- Revisar mojibake/encoding solo en archivos tocados.
- Validar matriz completa, rebuild del servicio principal y smokes HTTP minimos.

## Archivos previstos

- `docs/btdigg-rd/tanda-final-plan.md`
- `docs/btdigg-rd/tanda-final-informe.md`
- `app/motor/btdigg/rd_turbo_pro.py`
- `app/motor/btdigg/_motor_rd_retry.py`
- `app/motor/btdigg/_motor_qbt_probe.py`
- `app/motor/btdigg/_motor_exports.py`
- `tests/test_motor_characterization.py`
- `tests/test_motor_retry_contract.py`
- `tests/test_motor_qbt_probe_contract.py`
- `tests/test_motor_exports_contract.py`
- `tests/test_motor_prepare_contract.py`

## Riesgos

- `rd_turbo_pro.py` es monolitico y depende de globals de runtime, configuracion, RD, qB y diagnosticos.
- `prepare_results` y `rd_check_availability` tienen acoplamiento alto; si sacarlas crea fragilidad, se mantendran como wrappers/helpers internos.
- Las ramas de RD/qB deben testearse con stubs, sin red real y sin tocar `data/`.
- No se deben tocar `data/`, `config.json`, `rd_token.txt` ni `exports/` reales.

## Rollback

- Backup previo: `_backups/20260701-111948-tanda-final-motor.zip`.
- Base Git previa: `ce4a4e5 fix: clean residual mojibake`.
- Si falla una extraccion o aparece fragilidad alta, revertir solo el ultimo bloque editado y conservar lo seguro que quede verde.
- Si se rompe contrato publico, parar y no seguir acumulando cambios.

## Criterio de salida

- Wrappers publicos conservados: `rd_call_with_retry`, `qbt_probe_one`, `export_results`, `rd_check_availability`, `prepare_results`.
- Tests nuevos y existentes verdes.
- Sin red real ni qB/RD real en tests.
- Sin cambios de rutas HTTP, endpoints Flask ni claves JSON publicas.
- Runtime real intacto.
- Encoding limpio en archivos tocados.
- Rebuild `btdigg-rd` y smokes HTTP OK.
- Informe final completo y Git limpio tras commit local.

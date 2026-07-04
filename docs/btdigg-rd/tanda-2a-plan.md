# TANDA 2A - Plan conservador

## Objetivo

Reducir riesgo interno en `jobs.py`, `send.py` y `routes.py` con extracciones pequenas dentro de `app/api/btdigg_rd/`, manteniendo intactos endpoints, payloads, rutas runtime y fachadas publicas.

## Archivos previstos

- `tests/test_routes_contract.py`
- `tests/test_jobs_contract.py`
- `tests/test_send_contract.py`
- `tests/test_settings_contract.py`
- `app/api/btdigg_rd/_runtime_dirs.py`
- `app/api/btdigg_rd/_job_artifacts.py`
- `app/api/btdigg_rd/_rd_client.py`
- `app/api/btdigg_rd/_rdt_client.py`
- `app/api/btdigg_rd/_qbt_client.py`
- `app/api/btdigg_rd/_send_tracking.py`
- `app/api/btdigg_rd/_settings_service.py`
- `app/api/btdigg_rd/_tv_rules_service.py`
- `app/api/btdigg_rd/_ui_state_service.py`
- `app/api/btdigg_rd/jobs.py`
- `app/api/btdigg_rd/send.py`
- `app/api/btdigg_rd/routes.py`

## Riesgos

- `send.py` mezcla endpoint, clientes externos, tracking y decisiones RD/qB; las extracciones deben ser mecanicas y con wrappers.
- `jobs.py` comparte runtime, cancelacion, subproceso y promocion de artefactos; no se debe alterar la estructura real de `data/` sin tanda propia.
- `routes.py` contiene configuracion publica; cualquier cambio en claves JSON o metodos HTTP seria regresion.
- `rd_turbo_pro.py` queda fuera de alcance salvo documentar riesgos.

## Criterio de rollback

Si cambia un contrato publico, falla la matriz de pruebas, hace falta mover runtime real, tocar `rd_turbo_pro.py` de forma no trivial o modificar UI, parar la tanda y volver al estado anterior usando el commit previo o el backup `20260701-094147-tanda-2a-conservadora.zip`.

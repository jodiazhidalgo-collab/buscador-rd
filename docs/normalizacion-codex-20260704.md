# Normalizacion Codex 2026-07-04

## Objetivo

Cerrar una pasada conservadora de higiene y forma de trabajo Codex sin tocar motor, API funcional, UI, datos reales ni contratos publicos.

## Inventario revisado

- Raiz del proyecto y `git status --short`.
- `AGENTS.md`.
- `.agents/skills/` y scripts locales.
- `.gitignore` y `.dockerignore`.
- `_codex_runtime/`.
- `docs/`.
- `tests/`.
- `data/`.
- `app/api/btdigg_rd/`.
- `app/motor/btdigg/`.
- Servicio vivo `btdigg-rd` en puerto `9007`.

## Clasificacion

### Conservar sin discusion

- Codigo de `app/`.
- Tests de `tests/`.
- Documentacion existente en `docs/`.
- Skills locales de `.agents/skills/`.
- `.codex/` del proyecto.
- `data/` y diagnosticos reales.
- `_codex_runtime/` que siga siendo util para pruebas y artefactos.

### Limpieza segura

No se aplico borrado manual en esta pasada. El modo lectura de `limpiar-residuos-btdigg-rd` detecto `0` residuos seguros.

### Dudoso

- `data/diagnostics/btdigg/jobs`: contiene trazas reales y no se toca.
- `data/diagnostics/btdigg/rd_tests`: contiene ejecuciones RD test reales y no se toca.
- `_codex_runtime/artifacts`: puede contener evidencia de trabajo, no se borra sin necesidad.
- `.playwright-mcp`: runtime local ignorado por Git, no se borra en esta pasada.

### Normalizado

- `AGENTS.md`: se reforzaron fases, puertas de salida, clasificacion previa, regresion minima y reglas de no tocar motor/contratos.
- `.dockerignore`: se amplio para no mandar al contexto Docker Git, backups, runtime local, handoff grande, docs/tests y residuos.

## Que no se toco

- Motor funcional RD/qB/RDT.
- Endpoints, nombres Flask, payloads JSON y contratos publicos.
- UI visible.
- `data/`.
- `app/motor/btdigg/config.json`.
- `app/motor/btdigg/rd_token.txt`.
- Replicas `BTDigg + RD 2` y `BTDigg + RD 3`.
- Compose maestro.

## Verificacion esperada de cierre

- `git status --short`.
- Revision de `git diff`.
- `python -m compileall app tests`.
- Tests concretos de reglas/contratos si procede.
- `python -m pytest -q` si el entorno lo permite.
- Smoke HTTP de `9007`.
- Confirmar que `.gitignore` protege runtime/datos y que `.dockerignore` no excluye lo que Docker necesita.


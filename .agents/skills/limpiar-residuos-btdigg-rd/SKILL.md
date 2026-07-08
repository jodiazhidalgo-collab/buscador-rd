---
name: limpiar-residuos-btdigg-rd
description: Limpiar residuos seguros de Codex y pruebas en el proyecto unificado Z:\buscador-rd. Crea y mantiene _codex_runtime, evita que tests escriban en runtime real y borra solo basura sintetica conocida.
---

# Limpiar Residuos BTDigg + RD

## Cuando usarla

Usar dentro del cierre final de `cerrar-git-btdigg-rd`.

## Zonas

`config\btdigg-rd\data` es sagrado: solo datos reales de la app.

Codex debe usar:

- `_codex_runtime/tmp/`
- `_codex_runtime/test-data/`
- `_codex_runtime/artifacts/`

## Flujo

1. Confirmar raiz del proyecto.
2. Crear `_codex_runtime/tmp`, `_codex_runtime/test-data` y `_codex_runtime/artifacts` si faltan.
3. Borrar basura Python segura: `__pycache__`, `*.pyc`, `.pytest_cache`.
4. Borrar residuos sinteticos conocidos en `config\btdigg-rd\data\jobs` y `config\btdigg-rd\data\diagnostics\btdigg\jobs`.
5. Borrar carpetas vacias dentro de `_codex_runtime` salvo las raices `tmp`, `test-data` y `artifacts`.
6. Aplicar retencion a `_codex_runtime`: tmp/test-data 2 dias, artifacts 7 dias por defecto.
7. Informar que se borro y que se conservo.

## Comando

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\limpiar-residuos-btdigg-rd\scripts\clean_residues.ps1
```

Modo lectura:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\limpiar-residuos-btdigg-rd\scripts\clean_residues.ps1 -DryRun
```

## Reglas

- No borrar jobs reales con ids normales.
- No borrar `config\btdigg-rd\data\history`, exports reales, logs reales, tokens ni configuracion.
- Solo borrar patrones sinteticos de lista blanca: `job_cancel_*`, `codex_test_*`, `codex_tmp_*`, `unit_test_*`.
- Las carpetas vacias de `_codex_runtime` no son evidencia util: se borran siempre.
- Si hay duda, informar y no borrar.

# Revision IA de Buscador RD

Este documento es la guia publica y segura para revisar Buscador RD desde GitHub, ChatGPT, Codex o cualquier sandbox externa.

## Que debe mirar primero una IA

1. `README.md`: mapa publico del proyecto y verdad del flujo.
2. `diagnostics_public/`: espejo publico saneado del runtime real, jobs, logs, JSON, seguimiento, historial y errores.
3. `.github/workflows/ci.yml`: pruebas automaticas que GitHub ejecuta en cada push o pull request.
4. Artefacto `buscador-rd-pytest-evidence` de GitHub Actions: informe JUnit de pytest descargable.
5. `docs/evidencia-pytest-y-validacion-local.md`: como reproducir las pruebas desde cero.
6. `docker-compose.example.yaml` y `.env.example`: forma publica del despliegue, sin credenciales reales.
7. `services/btdigg-rd/tests/`: contratos de motor, RD/qB, jobs, UI state, voz y caja negra.

## Verdad tecnica del flujo

La fuente principal de estados, decisiones y errores debe salir de:

1. `diagnostics_public/` cuando la revision sea desde GitHub, ChatGPT o una sandbox externa.
2. runtime local definido por `DATA_DIR`
3. jobs bajo `jobs/<job_id>/`
4. diagnosticos bajo `diagnostics/btdigg`
5. modulos de seguimiento y caja negra en `services/btdigg-rd/app/api/btdigg_rd`
6. artefactos generados por cada job

No se deben inventar fuentes paralelas si esos datos ya pueden derivarse del runtime del job o de la caja negra.

## Diagnostico publico

`diagnostics_public/` es la copia publica saneada. Mantiene visibles busquedas, nombres, rutas, magnets, hashes, URLs, JSON, logs, estados RD/qB, errores y artefactos del job. Solo tapa tokens, passwords, API keys, Authorization, cookies y secretos equivalentes.

La app regenera esa carpeta al terminar jobs RD/BTDigg. Tambien se puede regenerar manualmente:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\export_public_diagnostics.ps1 -CheckSecrets
```

Despues de regenerar, GitHub/ChatGPT solo ve los cambios si se hace commit y push.

## Publicacion desde la web

La pantalla de Ajustes incluye un boton `Push`. En el despliegue real, ese boton:

1. regenera `diagnostics_public/`;
2. ejecuta `gitleaks` sobre el diagnostico publico y sobre los archivos preparados para commit;
3. respeta `.gitignore`, por lo que no fuerza runtime crudo ni secretos ignorados;
4. crea commit automatico solo si hay cambios;
5. hace push por SSH al repo `buscador-rd`.

La credencial de escritura es una deploy key SSH local y limitada a este repositorio. La ruta local `config/btdigg-rd/git/` no debe subirse a Git.

## Pruebas seguras

Desde la raiz del repo:

```powershell
python -m pip install -r services/btdigg-rd/requirements-dev.txt
python -m compileall -q services/btdigg-rd services/cloudflared
python -m pytest -q --junitxml _codex_runtime/artifacts/buscador-rd-pytest-junit.xml --durations=20
```

Los tests live quedan desactivados salvo que se definan variables explicitas como `BTDIGG_LIVE=1`.

## Que no esta en Git

Por seguridad, el repositorio publico no debe incluir:

- `.env`
- `docker-compose.yaml`
- `AGENTS.md`
- `.agents/`
- `.codex/`
- `_codex_runtime/`
- `_backups/`
- `.playwright-mcp/`
- `config/btdigg-rd/data/`
- `config/btdigg-rd/git/`
- `config/cloudflared/data/`
- `config/cloudflared/logs/`
- `config/cloudflared/config/public.env`
- `config/cloudflared/config/secrets.env`
- `config/whisper/data/`
- `config/whisper/logs/`
- tokens, modelos, bases de datos, logs, caches o ZIPs generados
- runtime crudo sin pasar por el exportador de `diagnostics_public/`

Si una IA necesita diagnosticar un fallo real, debe mirar `diagnostics_public/`, el artefacto de GitHub Actions o el resumen local de cierre, no secretos ni runtime crudo.

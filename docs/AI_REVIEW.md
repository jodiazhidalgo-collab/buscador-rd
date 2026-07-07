# Revision IA de Buscador RD

Este documento es la guia publica y segura para revisar Buscador RD desde GitHub, ChatGPT, Codex o cualquier sandbox externa.

## Que debe mirar primero una IA

1. `README.md`: mapa publico del proyecto y verdad del flujo.
2. `.github/workflows/ci.yml`: pruebas automaticas que GitHub ejecuta en cada push o pull request.
3. Artefacto `buscador-rd-pytest-evidence` de GitHub Actions: informe JUnit de pytest descargable.
4. `docs/evidencia-pytest-y-validacion-local.md`: como reproducir las pruebas desde cero.
5. `docker-compose.example.yaml` y `.env.example`: forma publica del despliegue, sin credenciales reales.
6. `services/btdigg-rd/tests/`: contratos de motor, RD/qB, jobs, UI state, voz y caja negra.

## Verdad tecnica del flujo

La fuente principal de estados, decisiones y errores debe salir de:

1. runtime definido por `DATA_DIR`
2. jobs bajo `jobs/<job_id>/`
3. diagnosticos bajo `diagnostics/btdigg`
4. modulos de seguimiento y caja negra en `services/btdigg-rd/app/api/btdigg_rd`
5. artefactos generados por cada job

No se deben inventar fuentes paralelas si esos datos ya pueden derivarse del runtime del job o de la caja negra.

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
- `config/cloudflared/data/`
- `config/cloudflared/logs/`
- `config/cloudflared/config/public.env`
- `config/cloudflared/config/secrets.env`
- `config/whisper/data/`
- `config/whisper/logs/`
- tokens, modelos, bases de datos, logs, caches o ZIPs generados

Si una IA necesita diagnosticar un fallo real, hay que darle el artefacto de GitHub Actions, un diagnostico saneado o el resumen local de cierre, no secretos ni datos privados sueltos.

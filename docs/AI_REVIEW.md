# Revision IA de Buscador RD

Este documento es la guia publica y segura para revisar Buscador RD desde GitHub, ChatGPT, Codex o cualquier sandbox externa.

## Mapa tecnico del proyecto

Buscador RD es el proyecto unificado para busqueda, disponibilidad RD/qBittorrent, seguimiento de jobs y dictado por voz con transcripcion local.

Piezas principales:

- Web principal: `services/btdigg-rd`
- HTTPS movil y tunel: `services/cloudflared`
- Transcripcion local: servicio `whisper` declarado en `docker-compose.example.yaml`
- Compose publico: `docker-compose.example.yaml`
- Configuracion publica de ejemplo: `.env.example`

El compose real, tokens, modelos, backups y runtime crudo no forman parte del Git publico. Para revision externa se publica un espejo saneado en `diagnostics_public/`, con secretos tapados y datos de diagnostico visibles.

## Que debe mirar primero una IA

1. `README.md`: portada minima del repositorio.
2. `AGENTS.md`: reglas publicas de trabajo, raiz real, rutas importantes y cierre Git.
3. `.agents/skills/`: workflows reutilizables del repo, con scripts seguros y sin secretos.
4. `diagnostics_public/`: espejo publico saneado del runtime real, jobs, logs, JSON, seguimiento, historial y errores.
5. `.github/workflows/ci.yml`: pruebas automaticas que GitHub ejecuta en cada push o pull request.
6. Artefacto `buscador-rd-pytest-evidence` de GitHub Actions: informe JUnit de pytest descargable.
7. `docs/evidencia-pytest-y-validacion-local.md`: como reproducir las pruebas desde cero.
8. `docker-compose.example.yaml` y `.env.example`: forma publica del despliegue, sin credenciales reales.
9. `services/btdigg-rd/tests/`: contratos de motor, RD/qB, jobs, UI state, voz y caja negra.

## Skills publicas del proyecto

Las skills del repo viven en `.agents/skills/` y se versionan en Git para que Codex, ChatGPT o una revision externa puedan ver el mismo flujo operativo que se usa en local.

Regla limpia:

- `.agents/skills/` si va a Git.
- `.agents/` fuera de `skills` no va a Git.
- `.codex/` sigue siendo local y privado.
- Los scripts de skills no deben contener tokens, passwords, API keys, cookies ni credenciales.
- Para pedir una investigacion avanzada externa, usar `.agents/skills/investigacion-avanzada-buscador-rd/`.

## Verdad tecnica del flujo

La fuente principal de estados, decisiones y errores debe salir de:

1. `diagnostics_public/` cuando la revision sea desde GitHub, ChatGPT o una sandbox externa.
2. runtime local definido por `DATA_DIR`
3. jobs bajo `jobs/<job_id>/`
4. diagnosticos bajo `diagnostics/btdigg`
5. modulos de seguimiento y caja negra en `services/btdigg-rd/app/api/btdigg_rd`
6. artefactos generados por cada job

No se deben inventar fuentes paralelas si esos datos ya pueden derivarse del runtime del job o de la caja negra.

La UI visible manda cuando el problema es de botones, pestanas, busqueda, voz o seguimiento.

## Diagnostico publico

`diagnostics_public/` es la copia publica saneada. Mantiene visibles busquedas, nombres, rutas, magnets, hashes, URLs, JSON, logs, estados RD/qB, errores y artefactos del job. Solo tapa tokens, passwords, API keys, Authorization, cookies y secretos equivalentes.

La app no regenera esa carpeta al terminar cada busqueda normal. El runtime local conserva la caja negra real y `diagnostics_public/` se regenera bajo demanda para revision externa, Push o export manual:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\export_public_diagnostics.ps1
```

Despues de regenerar, GitHub/ChatGPT solo ve los cambios si se hace commit y push.

## Publicacion desde la web

La pantalla de Ajustes incluye un boton `Push`. En el despliegue real, ese boton:

1. regenera `diagnostics_public/`;
2. respeta `.gitignore`, por lo que no fuerza runtime crudo ni datos ignorados;
3. crea commit automatico solo si hay cambios;
4. hace push por SSH al repo `buscador-rd`;
5. refresca `origin/master` y confirma que coincide con `HEAD`.

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
- `.agents/` fuera de `.agents/skills/`
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

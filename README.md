# Buscador RD

Buscador RD es el proyecto unificado para buscar torrents, revisar disponibilidad en Real-Debrid, enviar enlaces a RD/qBittorrent, seguir jobs y usar dictado por voz con un transcriptor local.

## Piezas principales

- Web principal: `services/btdigg-rd`
- HTTPS movil y tunel: `services/cloudflared`
- Transcripcion local: servicio `whisper` declarado en `docker-compose.example.yaml`
- Compose publico: `docker-compose.example.yaml`
- Configuracion publica de ejemplo: `.env.example`

El compose real, tokens, modelos, backups y runtime crudo no forman parte del Git publico. Para revision externa se publica un espejo saneado en `diagnostics_public/`, con secretos tapados y datos de diagnostico visibles.

## Verdad del flujo

Para revisar un fallo, empieza por la caja negra y los artefactos del job:

1. `diagnostics_public/` si estas revisando desde GitHub, ChatGPT o una sandbox externa.
2. runtime local definido por `DATA_DIR` si estas dentro de la maquina.
3. jobs bajo `jobs/<job_id>/`
4. diagnosticos bajo `diagnostics/btdigg`
5. sidecars y artefactos de `services/btdigg-rd/app/api/btdigg_rd`
6. solo despues, logs sueltos o codigo

La UI visible manda cuando el problema es de botones, pestanas, busqueda, voz o seguimiento.

`diagnostics_public/` se regenera al terminar jobs RD/BTDigg y tambien se puede regenerar manualmente con:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\export_public_diagnostics.ps1 -CheckSecrets
```

Para que ChatGPT lo vea desde GitHub, despues de regenerar hay que hacer commit y push.

## Push desde la web

En Ajustes existe un boton `Push` para publicar el estado actual del proyecto en GitHub desde la propia web. El flujo real es:

1. regenerar `diagnostics_public/`;
2. pasar `gitleaks`;
3. preparar solo archivos permitidos por `.gitignore`;
4. crear commit si hay cambios;
5. hacer push a `master`.

El despliegue real usa una deploy key SSH local de solo este repo. La key vive fuera de Git en `config/btdigg-rd/git/`; el compose publico solo documenta el montaje.

## Revision IA

Lee tambien:

- `AGENTS.md`: instrucciones publicas del repo para Codex/ChatGPT y reglas de trabajo.
- `.agents/skills/`: workflows reutilizables del proyecto, con scripts seguros y sin secretos.
- `docs/AI_REVIEW.md`: guia publica para ChatGPT, Codex o revisiones externas.
- `docs/evidencia-pytest-y-validacion-local.md`: pruebas pytest, comandos y evidencia local.
- `.github/workflows/ci.yml`: CI publico con informe JUnit descargable.

## Desarrollo local

```powershell
python -m pip install -r services/btdigg-rd/requirements-dev.txt
python -m compileall -q services/btdigg-rd services/cloudflared
python -m pytest -q
```

Los tests live quedan saltados salvo que se activen variables explicitas de entorno. Los datos reales crudos, backups, runtime y caches quedan fuera de Git por `.gitignore`; el diagnostico publico saneado vive en `diagnostics_public/`.

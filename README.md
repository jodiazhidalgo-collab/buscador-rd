# Buscador RD

Buscador RD es el proyecto unificado para buscar torrents, revisar disponibilidad en Real-Debrid, enviar enlaces a RD/qBittorrent, seguir jobs y usar dictado por voz con un transcriptor local.

## Piezas principales

- Web principal: `services/btdigg-rd`
- HTTPS movil y tunel: `services/cloudflared`
- Transcripcion local: servicio `whisper` declarado en `docker-compose.example.yaml`
- Compose publico: `docker-compose.example.yaml`
- Configuracion publica de ejemplo: `.env.example`

El compose real, tokens, datos vivos, modelos, logs y backups no forman parte del Git publico.

## Verdad del flujo

Para revisar un fallo, empieza por la caja negra y los artefactos del job:

1. runtime definido por `DATA_DIR`
2. jobs bajo `jobs/<job_id>/`
3. diagnosticos bajo `diagnostics/btdigg`
4. sidecars y artefactos de `services/btdigg-rd/app/api/btdigg_rd`
5. solo despues, logs sueltos o codigo

La UI visible manda cuando el problema es de botones, pestanas, busqueda, voz o seguimiento.

## Revision IA

Lee tambien:

- `docs/AI_REVIEW.md`: guia publica para ChatGPT, Codex o revisiones externas.
- `docs/evidencia-pytest-y-validacion-local.md`: pruebas pytest, comandos y evidencia local.
- `.github/workflows/ci.yml`: CI publico con informe JUnit descargable.

## Desarrollo local

```powershell
python -m pip install -r services/btdigg-rd/requirements-dev.txt
python -m compileall -q services/btdigg-rd services/cloudflared
python -m pytest -q
```

Los tests live quedan saltados salvo que se activen variables explicitas de entorno. Los datos reales, backups, diagnosticos locales, runtime y caches quedan fuera de Git por `.gitignore`.

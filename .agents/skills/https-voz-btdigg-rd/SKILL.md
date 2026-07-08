---
name: https-voz-btdigg-rd
description: Mapa del flujo de voz, microfono, HTTPS, Cloudflared, Whisper y resolver de titulos de BTDigg + RD. Usar cuando la tarea mencione micro, audio, voz, dictado, transcripcion, boton de microfono, HTTPS movil, Cloudflare, Cloudflared, Whisper, resolver o biblioteca de titulos.
---

# HTTPS Voz BTDigg RD

## Cuando usarla

Usa esta skill antes de tocar o diagnosticar cualquier cosa relacionada con el boton de microfono, grabacion de audio, transcripcion, HTTPS movil, Cloudflared, Whisper o resolucion de titulos en BTDigg + RD.

## Mapa real

- Raiz unificada: `Z:\buscador-rd`.
- Compose del conjunto: `Z:\buscador-rd\docker-compose.yaml` / `/volume1/docker/buscador-rd/docker-compose.yaml`.
- Codigo web principal: `Z:\buscador-rd\services\btdigg-rd`.
- Servicio web: `btdigg-rd`, puerto `9007`.
- Servicio HTTPS/tunel: `cloudflared`.
- Codigo Cloudflared: `Z:\buscador-rd\services\cloudflared`.
- Runtime Cloudflared: `Z:\buscador-rd\config\cloudflared`.
- Servicio transcriptor local: `whisper`, puerto `9017`.
- Runtime Whisper/modelos/logs: `Z:\buscador-rd\config\whisper`.
- El micro del movil debe probarse por HTTPS. Por `http://192.168.1.159:9007/` puede fallar por contexto no seguro.

## Archivos clave BTDigg

- Frontend voz: `services\btdigg-rd\app\web\static\js\btdigg-rd.js`.
- Rutas API voz: `services\btdigg-rd\app\api\btdigg_rd\routes.py`.
- Transcripcion: `services\btdigg-rd\app\api\btdigg_rd\voice_transcription.py`.
- Diagnostico voz: `services\btdigg-rd\app\api\btdigg_rd\voice_diagnostics.py`.
- Configuracion voz: `services\btdigg-rd\app\api\btdigg_rd\config.py`.
- Resolver/biblioteca de titulos: `services\btdigg-rd\app\api\btdigg_rd\title_resolver\`.
- Cache del resolver: `config\btdigg-rd\data\title_resolver.sqlite3`.
- API del resolver: `POST /api/title-resolver/resolve` en `services\btdigg-rd\app\api\btdigg_rd\routes.py`.
- Tests de contrato: `services\btdigg-rd\tests\test_voice_diagnostics_contract.py` y `services\btdigg-rd\tests\test_routes_contract.py`.

## Archivos clave Cloudflared

- Supervisor: `services\cloudflared\supervisor.py`.
- Watcher: `services\cloudflared\watcher\app\watcher.py`.
- Worker: `services\cloudflared\worker\gateway_worker.js`.
- Config publica/privada: `config\cloudflared\config`.
- Logs: `config\cloudflared\logs`.
- Estado/enlace actual: `config\cloudflared\data\estado`.

## Configuracion esperada

En `Z:\buscador-rd\docker-compose.yaml`, servicio `btdigg-rd`, deben existir estas variables:

```text
BTDIGG_VOICE_TRANSCRIBE_PROVIDER=openai
BTDIGG_VOICE_OPENAI_BASE_URL=http://whisper:9000/v1
BTDIGG_VOICE_OPENAI_API_KEY=local-whisper
BTDIGG_VOICE_OPENAI_MODEL=whisper-1
BTDIGG_VOICE_TRANSCRIBE_TIMEOUT_SEC=60
```

El servicio `whisper` expone normalmente `9017:9000`.

El servicio `cloudflared` debe apuntar al BTDigg principal:

```text
TUNNEL_TARGET=http://192.168.1.159:9007
```

## Caja negra

- La caja negra de voz va separada de RD/qB.
- Buscar eventos `voice_*`, `micro_*` o rutas bajo diagnostico de voz.
- El flujo de voz registra tambien `voice_resolver_start`, `voice_resolver_ok` y `voice_resolver_error` cuando consulta la biblioteca/resolver.
- No mezclar fallos de micro con scoring, RD, qBit ni motor BTDigg salvo evidencia directa.
- Los logs de Cloudflared y Whisper viven fuera del repo, en `Z:\buscador-rd\config`.

## Flujo de voz real

1. El frontend graba audio con `MediaRecorder` desde el boton `voiceQueryBtn`.
2. Envia el audio a `POST /api/voice/transcribe`.
3. BTDigg llama al Whisper local usando API compatible OpenAI.
4. Con el texto transcrito, el frontend llama a `POST /api/title-resolver/resolve`.
5. Si el resolver devuelve `status=resolved` y `safe=true`, rellena `bQuery` con titulo limpio y ano. Si no esta claro, deja el texto transcrito y marca "No seguro". No lanza BUSCAR automaticamente.

## Flujo recomendado

1. Leer `AGENTS.md` y ejecutar `git status --short`.
2. Revisar `Z:\buscador-rd\docker-compose.yaml` si el fallo huele a HTTPS, Cloudflared o Whisper.
3. Revisar `btdigg-rd.js`, `routes.py`, `voice_transcription.py`, `voice_diagnostics.py` y `title_resolver`.
4. Si se cambia frontend, backend o compose, hacer backup primero y validar con rebuild o contenedores segun toque.
5. Para el movil, probar desde la URL HTTPS de Cloudflared, no desde HTTP local.

# Instrucciones para Codex - "Z:\buscador-rd"

Eres "Apanado". Responde siempre en espanol y empieza siempre por:

`Pim Pam`

## Raiz real

La raiz del proyecto es siempre:

```text
Z:\buscador-rd
/volume1/docker/buscador-rd
```

No centres memoria, Git, backups ni skills en `services\btdigg-rd`. Esa carpeta es solo un servicio dentro del conjunto.

## Proyecto unificado

Este proyecto agrupa tres piezas:

- Web principal: `services\btdigg-rd` / contenedor `btdigg-rd` / puerto `9007`.
- HTTPS movil y tunel: `services\cloudflared` + `config\cloudflared` / contenedor `cloudflared`.
- Transcripcion local: `config\whisper` / contenedor `whisper` / puerto `9017`.

Compose maestro:

```text
Z:\buscador-rd\docker-compose.yaml
/volume1/docker/buscador-rd/docker-compose.yaml
```

El compose real es local y puede llevar credenciales. Para Git y revision externa usa:

```text
Z:\buscador-rd\docker-compose.example.yaml
```

Rutas importantes:

- Web local: `http://192.168.1.159:9007`
- Whisper local: `http://192.168.1.159:9017`
- SSH NAS: `lacabra@192.168.1.159`
- Runtime BTDigg: `config\btdigg-rd\data`
- Diagnostico publico saneado: `diagnostics_public`
- Runtime del motor BTDigg: `config\btdigg-rd\data\motor` (`config.json`, `rd_token.txt`, `exports`)
- Runtime Cloudflared: `config\cloudflared`
- Runtime Whisper: `config\whisper`

## Reglas de trabajo

- Antes de tocar, ejecuta `git status --short` desde `Z:\buscador-rd`.
- Si modificas cualquier archivo del proyecto, cierra el turno con `cerrar-git-btdigg-rd` desde `Z:\buscador-rd`: limpieza segura, commit y push al remoto configurado.
- No dejes cambios locales sin commit/push salvo que el usuario pida expresamente no cerrar Git.
- Las skills del proyecto viven en `Z:\buscador-rd\.agents\skills`.
- La configuracion Codex del proyecto vive en `Z:\buscador-rd\.codex`.
- Los backups se hacen solo en `Z:\buscador-rd\_backups`.
- No crees backups dentro de `services\btdigg-rd`, `config\cloudflared`, `config\whisper` ni otra subcarpeta.
- No metas pruebas falsas en `config\btdigg-rd\data`.
- No subas secretos, tokens, modelos ni runtime crudo a Git.
- Si hace falta que ChatGPT/GitHub vea datos reales, usa `diagnostics_public`, que es el espejo saneado.
- No uses `git reset`, `git checkout` ni comandos destructivos salvo peticion explicita.
- `AGENTS.md` y `.agents\skills\` son parte publica del flujo: deben ir a Git para que Codex, ChatGPT o cualquier revision externa entiendan como trabajar este repo.
- `.agents\` sigue siendo privada para cualquier otra cosa que no sea `skills`.

## Skills

- Cambios delicados: usa `backup-btdigg-rd` antes.
- Errores RD, qB, seguimiento o caja negra: usa `blackbox-review-btdigg-rd`.
- UI visible: usa `playwright-ui-check-btdigg-rd`.
- Rebuild/validacion del servicio web: usa `rebuild-btdigg-rd`.
- Micro, voz, dictado, HTTPS, Cloudflare, Cloudflared o Whisper: usa `https-voz-btdigg-rd`.
- Limpieza segura: usa `limpiar-residuos-btdigg-rd`.
- Cierre Git local: usa `cerrar-git-btdigg-rd`.
- Replicas 2/3: usa `replicate-btdigg-rd` solo con permiso explicito.
- Investigacion avanzada externa: usa `investigacion-avanzada-buscador-rd`.

## Investigacion avanzada externa

Si el usuario pide investigacion avanzada, deep research, prompt para ChatGPT,
"pasame lo que tengo que pegar", "que lo mire ChatGPT" o algo equivalente sobre
Buscador RD, usa `investigacion-avanzada-buscador-rd`.

El prompt generado debe indicar siempre:

- repo GitHub: `jodiazhidalgo-collab/buscador-rd`;
- rama: `master`;
- mirar primero `README.md`, `AGENTS.md`, `docs/AI_REVIEW.md`,
  `.agents/skills/`, `.github/workflows/ci.yml`, `services/btdigg-rd/tests/`
  y `diagnostics_public/`;
- adaptar el motivo al problema concreto del usuario;
- no devolver el repo entero ni secretos;
- recordar que datos vivos recientes solo aparecen en GitHub despues de hacer
  `Push`.

## Git

Git se gestiona desde la raiz:

```text
Z:\buscador-rd
```

Si trabajas dentro de `services\btdigg-rd`, no cierres Git desde ahi como si fuera otro proyecto. Vuelve a la raiz antes de status, commit, cierre o limpieza.

Despues de cualquier cambio aprobado, el cierre normal es:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\cerrar-git-btdigg-rd\scripts\close_git.ps1 -Message "mensaje corto"
```

Mantener fuera de Git:

- `_backups/`
- `_codex_runtime/`
- `.agents/*` salvo `.agents/skills/`
- `.codex/`
- `.playwright-mcp/`
- `docker-compose.yaml`
- `config\btdigg-rd\data/`
- `config\cloudflared\data/`
- `config\cloudflared\logs/`
- `config\cloudflared\config\public.env`
- `config\cloudflared\config\secrets.env`
- `config\whisper\data/`
- `config\whisper\logs/`
- `services/**/_backups/`
- `services/**/data/`
- `services/**/logs/`
- `services/**/__pycache__/`
- `**/__pycache__/`
- `*.pyc`
- `*.log`
- `*.tmp`
- `*.zip`
- `*.lnk`

Excepcion permitida:

- `diagnostics_public/` puede ir a Git porque sale del exportador saneado. No sustituye al runtime crudo; es la copia publica para IA.

Ficheros de proyecto que viven en la raiz:

- `AGENTS.md`
- `.gitattributes`
- `.gitignore`
- `.agents/skills/`
- `.github/`
- `.githooks/`
- `README.md`
- `docs/`
- `pytest.ini`
- `docker-compose.example.yaml`

## BTDigg + RD

Codigo principal:

```text
Z:\buscador-rd\services\btdigg-rd
/volume1/docker/buscador-rd/services/btdigg-rd
```

Aqui vive la app principal:

```text
app/app.py
requirements.txt
Dockerfile
app/web/templates/index.html
app/web/static/css/
app/web/static/js/
tests/
```

El codigo del motor vive en:

```text
services\btdigg-rd\app\motor\btdigg
```

Esa carpeta es codigo. No guardes ahi `config.json`, `rd_token.txt`, `exports`, `last_links.txt` ni otros datos vivos.

Datos reales de la app:

```text
Z:\buscador-rd\config\btdigg-rd\data
/volume1/docker/buscador-rd/config/btdigg-rd/data
```

Diagnostico publico para IA:

```text
Z:\buscador-rd\diagnostics_public
/volume1/docker/buscador-rd/diagnostics_public
```

Esa carpeta se regenera al terminar jobs RD/BTDigg y mantiene visibles logs,
JSON, jobs, busquedas, magnets, hashes, rutas, URLs y errores. Solo debe tapar
tokens, passwords, API keys, Authorization, cookies y secretos equivalentes.
Para regenerarla manualmente:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\export_public_diagnostics.ps1
```

Datos reales del motor:

```text
Z:\buscador-rd\config\btdigg-rd\data\motor
/volume1/docker/buscador-rd/config/btdigg-rd/data/motor
```

Reglas especificas:

- No crees `AGENTS.md` dentro de servicios salvo permiso explicito.
- No cierres Git desde `services\btdigg-rd`.
- No crees `_backups` dentro de `services\btdigg-rd`.
- Si cambias UI, valida visualmente.
- Si la tarea menciona micro, voz, HTTPS, Cloudflare, Cloudflared o Whisper, usa `https-voz-btdigg-rd`.
- Si la tarea menciona RD, qB, seguimiento o caja negra, usa `blackbox-review-btdigg-rd`.
- Si la tarea es revision externa o ChatGPT/GitHub debe ver fallos reales, revisa y actualiza `diagnostics_public/`.

## Replicas externas

Estas replicas no forman parte del trabajo normal de la raiz:

- `Z:\web\BTDigg + RD 2` / `btdigg-rd-2` / `9027`
- `Z:\web\BTDigg + RD 3` / `btdigg-rd-3` / `9037`

No repliques cambios a esas carpetas salvo permiso claro del usuario.


## Validacion

Si cambias frontend, backend, Docker o configuracion funcional:

1. Backup en `Z:\buscador-rd\_backups`.
2. Prueba local o Docker segun toque.
3. Si afecta a UI, prueba visual real.
4. Cierre con estado Git desde `Z:\buscador-rd`.

## Revision externa y hoja de cierre

Antes de cerrar Git en cualquier trabajo con cambios, actualiza:

```text
Z:\buscador-rd\.codex\review\latest.md
```

Ese archivo es la entrada local de cierre para Codex y complementa la capa
publica de GitHub:

- `README.md`
- `docs\AI_REVIEW.md`
- `diagnostics_public\`
- `docs\evidencia-pytest-y-validacion-local.md`
- `.github\workflows\ci.yml`
- artefacto `buscador-rd-pytest-evidence`

Debe quedar breve, claro y verificable, con:

- que pidio el usuario;
- que se cambio;
- archivos tocados;
- pruebas ejecutadas y resultado;
- commit/push si aplica;
- pendiente real o cosa que no se pudo comprobar.

Reglas:

- No metas secretos, tokens, logs completos ni rutas runtime sensibles.
- No conviertas `.codex\review\latest.md` en Pull Request ni en sistema grande.
- GitHub Actions si existe para pruebas publicas, informe JUnit y evidencia descargable.
- Si el informe se crea retroactivamente para el ultimo trabajo importante,
  dilo dentro del propio informe.
- Si no hubo cambios de codigo, aun asi deja claro que se actualizo el flujo
  de cierre y como se verifico.

## Cierre

Respuesta final breve, en espanol, indicando:

- archivos tocados
- pruebas hechas
- si queda algo pendiente

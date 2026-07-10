# Configuración y comportamiento completo de Real-Debrid

Este es el contrato funcional vigente de Real-Debrid. Cualquier cambio de su
comportamiento efectivo debe actualizar este documento en el mismo cambio. El
flujo exterior que consume estas decisiones se documenta en
[`flujo-descarga-rd-qb.md`](flujo-descarga-rd-qb.md).

## 1. Objetivo y límite de este documento

Este documento describe exclusivamente el contrato de comportamiento de
Real-Debrid (RD) usado para recibir, comprobar, aceptar, rechazar y limpiar un
magnet o un archivo `.torrent`.

Está escrito para poder trasladar este criterio a otro proyecto distinto. No
describe la web, la obtención de resultados, la interfaz, la cola de búsquedas,
la clasificación de películas/series ni el funcionamiento general de
Buscador RD.

La verdad documentada es el comportamiento efectivo del código y de la
configuración activa, no comentarios antiguos ni opciones que ya no participan
en las decisiones.

## 2. Principio de seguridad

Un torrent no se considera bueno solo porque:

- tenga un hash válido;
- aparezca en `instantAvailability`;
- RD acepte `addMagnet` o `addTorrent`;
- RD devuelva un identificador de torrent;
- alcance `waiting_files_selection`;
- tenga metadatos o seeders.

El criterio positivo efectivo depende de la rama:

- `addMagnet` exige enlaces reales y estado `downloaded`, `compressing` o
  `uploading`, o que el progreso convertido a texto sea exactamente `100` o
  `100.0`;
- `addTorrent` selecciona archivos, obtiene los enlaces, intenta
  `unrestrict/link` y considera positivo que quede al menos una descarga
  desrestringida; esa rama no vuelve a exigir estado o progreso.

Por tanto, recibir un ID nunca basta, pero las dos ramas no comparten actualmente
una única función de aceptación.

Con la configuración actual, un positivo de `instantAvailability` siempre se
confirma después mediante `addMagnet`. Por eso el positivo definitivo normal es
`RD_OK`, no el simple `RD_INSTANT`.

## 3. Entradas admitidas

### 3.1 Magnet

Debe contener un infohash BTIH extraíble. El proceso normal es:

1. Extraer y normalizar el hash.
2. Consultar `GET /torrents/instantAvailability/{hash}` cuando el endpoint está
   disponible.
3. Si parece instantáneo, confirmarlo mediante `POST /torrents/addMagnet`.
4. Leer `GET /torrents/info/{id}`.
5. Si RD pide selección, ejecutar `POST /torrents/selectFiles/{id}`.
6. Aceptar solo si aparecen enlaces reales y el estado/progreso es útil.

Si falta el magnet se devuelve `SIN_MAGNET`. Si existe magnet pero no puede
obtenerse un hash se devuelve `SIN_HASH` antes de gastar una comprobación RD.

### 3.2 URL de archivo `.torrent`

La URL puede pasar por una materialización previa antes de enviarla a RD:

1. Se descarga el contenido binario con timeout.
2. El probe acepta contenido por tipo MIME BitTorrent, extensión `.torrent` o
   firma parcial de bytes con diccionario e indicador `info`; no decodifica y
   valida obligatoriamente todo el bencode.
3. Se envían los bytes con `PUT /torrents/addTorrent` y tipo
   `application/x-bittorrent`.
4. RD debe devolver un `id`.
5. Se consulta el estado, se seleccionan archivos y se esperan enlaces.
6. Cada enlace RD resultante se convierte mediante `POST /unrestrict/link` al
   preparar una descarga directa.

La materialización previa se aplica como máximo a
`torrent_candidate_probe_max`. Los siguientes quedan `NO_VERIFICADO` en esa
fase, pero el bucle RD actual no bloquea ese estado: todavía puede descargar y
enviar URLs posteriores hasta el límite propio de la rama `.torrent`. Esta es
una diferencia efectiva entre “probe previo” y “verificación RD”, no una
garantía de bencode completo.

### 3.3 Torrent ya existente en la cuenta RD

Antes de crear otro torrent, se precarga e indexa la lista de torrents de la
cuenta por hash. Solo se reutiliza como positivo un elemento que:

- tenga el mismo hash;
- esté en estado `downloaded`;
- contenga enlaces;
- tenga información recuperable;
- y obtenga la mejor coincidencia disponible entre título, archivos internos y
  términos buscados.

Cuando cumple esas condiciones se marca `RD_OK` con `rd_existing=true` y se
conserva su identificador. Esa clase de existente descargado queda protegida de
la limpieza.

El error 33 tiene otra ruta: puede recuperar un torrent activo por hash y
reutilizar su ID sin marcarlo como existente protegido. Si después no produce
links, el flujo actual puede tratarlo como temporal `NO_INSTANT` e intentar
borrarlo. No debe confundirse esta limitación con la protección de los
existentes descargados precargados.

### 3.4 Torrent individual

RD puede pedir `waiting_files_selection` incluso para un torrent de un solo
archivo. El comportamiento efectivo no hace una excepción: obtiene la lista de
archivos y envía `files=all`. Después vuelve a consultar `info` y exige enlaces
reales para declararlo `RD_OK`.

### 3.5 Pack o torrent con varios archivos

El motor calcula contadores y tamaños sobre todos los archivos y conserva en la
instantánea diagnóstica el detalle de como máximo 24 filas:

- identificador;
- ruta;
- tamaño en GiB;
- tipo (`video`, `subtitle`, `text`, `image`, `archive` u `other`);
- si parece extra, tráiler o sample;
- coincidencia con los términos buscados;
- y selección informada por RD.

Los archivos adicionales se cuentan como omitidos. Esta instantánea sirve para
diagnóstico, tamaño y trazabilidad. La selección efectiva actual es:

```text
files=all
selection_mode=all
file_name=todos los archivos
```

Por tanto, un pack selecciona todo: vídeo principal, episodios, extras,
subtítulos, imágenes y demás contenido incluido por RD. Si otro proyecto quiere
replicar exactamente esta configuración debe enviar `all`; si quiere selección
inteligente por archivo, eso sería un comportamiento diferente.

`file_name=todos los archivos` pertenece al payload diagnóstico de la decisión.
El resultado operativo guarda `selected_file_ids=all`, deja
`selected_file_name` vacío deliberadamente y usa como tamaño seleccionado la
suma del contenido elegido, no el tamaño de un archivo concreto.

Solo cuando el contrato de entrada ya contiene `selected_file_ids` explícitos
se envían esos IDs en lugar de `all`.

## 4. Secuencia completa de comprobación

### 4.1 Validación del acceso RD

1. Debe existir un token, leído desde el runtime o la variable prevista por el
   servicio. El token nunca se registra ni se publica.
2. Se realiza un healthcheck contra RD.
3. Sin token, todos los candidatos RD quedan `SIN_TOKEN`.
4. Si RD rechaza el token o no responde al healthcheck, quedan
   `RD_TOKEN_ERROR` y se aborta el lote RD.

### 4.2 Preparación de candidatos

Antes de RD quedan fuera los `.torrent` que el probe sí inspeccionó y clasificó
como inválidos, los enlaces directos inválidos y los elementos sin identidad
utilizable. Un `.torrent` que excedió el máximo del probe puede continuar por la
ruta RD, como se describe en 3.2.

`verify_max_candidates` no es actualmente un presupuesto global. Limita el lote
de magnets cuando `instantAvailability` está desactivado y limita la rama
`.torrent`; cuando `instantAvailability` funciona, cada `RD_INSTANT` puede pasar
a `addMagnet` sin aplicar ese tope. `NO_VERIFICADO` significa fuera de un límite
concreto, no torrent muerto.

### 4.3 Consulta rápida de caché

Para cada magnet con hash se consulta `instantAvailability`:

- respuesta con variantes: estado provisional `RD_INSTANT`;
- respuesta sin entrada para el hash: `NO_CACHE`;
- endpoint desactivado, error 37: se desactiva temporalmente esta ruta durante
  900 segundos y se pasa a verificación directa por `addMagnet`;
- error no temporal distinto: `RD_ERROR`;
- error temporal agotado: se conserva como `RD_ERROR_TEMPORAL` cuando ocurre en
  la verificación seria.

El tamaño calculado desde `instantAvailability` es orientativo. No sustituye la
confirmación posterior.

### 4.4 Verificación seria mediante `addMagnet`

Con la configuración actual, todo `RD_INSTANT` se verifica así:

1. Buscar primero el mismo hash ya descargado en RD.
2. Reservar capacidad activa si el control de slots está habilitado.
3. Enviar `POST /torrents/addMagnet`.
4. Exigir que RD devuelva un `id`.
5. Registrar ese `id` como temporal.
6. Consultar `GET /torrents/info/{id}`.
7. Aplicar descarte rápido si aparece un fallo terminal inequívoco.
8. Si el estado es `waiting_files_selection`, enviar `files=all` una sola vez.
9. Esperar 0,25 segundos y realizar una lectura adicional inmediata.
10. Aceptar solo con enlaces y estado/progreso útil.
11. Si no llega a positivo en el intento configurado, marcar `NO_INSTANT` y
    borrar el torrent temporal.

Aunque el lote permite hasta 60 workers, los endpoints destructivos o sensibles
están regulados por límites independientes: solo entra un `addMagnet`, un
`selectFiles` y un borrado simultáneos. Las lecturas de `info` permiten cuatro.

### 4.5 Verificación mediante `addTorrent`

Para un `.torrent` real:

1. Descargar y validar los bytes.
2. Enviar `PUT /torrents/addTorrent`.
3. Exigir un `id`.
4. Consultar `info` hasta 15 veces.
5. Si aparece `waiting_files_selection`, seleccionar una sola vez:
   IDs explícitos si existen; en otro caso, `all`.
6. Esperar dos segundos entre consultas de esta fase.
7. Exigir al menos un enlace.
8. Si no aparecen enlaces, clasificar como `NO_INSTANT` cuando el mensaje indica
   que sigue pendiente; los errores temporales pasan a `RD_ERROR_TEMPORAL` y los
   restantes a `RD_ERROR`. Esta función no produce `RD_FAIL`.
9. Borrar el torrent temporal si la verificación falla.

### 4.6 Confirmación positiva

Un candidato confirmado queda con:

- `rd_status=RD_OK`;
- número de enlaces en `rd_links`;
- identificador en `rd_torrent_id`;
- tamaño conocido, si RD lo facilita;
- datos de selección y archivos para trazabilidad;
- `rd_existing=true` únicamente si ya estaba descargado en la cuenta.

Un identificador temporal marcado como positivo no se elimina en la limpieza
del lote porque todavía puede utilizarse para convertir sus enlaces. Después,
`cleanup_unselected_verified=true` limpia los positivos temporales incluidos en
la lista `shown`. Los positivos que no llegaron a `shown`, incluido un exceso
sobre el límite visible o una cancelación anterior a esa fase, no entran en esa
segunda limpieza. Los existentes descargados con `rd_existing=true` se excluyen;
la ruta especial de error 33 conserva la limitación descrita en 3.3.

## 5. Estados y decisiones

| Estado | Significado efectivo | ¿Es válido? | Acción |
|---|---|---:|---|
| `RD_OK` | RD ha entregado enlaces reales mediante verificación seria o reutilización segura | Sí | Conservar evidencia y permitir la salida RD |
| `RD_INSTANT` | `instantAvailability` dio positivo sin confirmación seria | Solo provisional | Con la configuración actual pasa inmediatamente por `addMagnet` y normalmente termina en otro estado |
| `NO_CACHE` | El hash no aparece en la caché instantánea | No para RD | No se presenta como RD válido; queda disponible para la frontera externa si existe otra estrategia |
| `NO_INSTANT` | RD aceptó el torrent pero no entregó enlaces útiles a tiempo, no tiene seeders o quedó sin progreso | No | Borrar el temporal y no fingir un positivo |
| `RD_FAIL` | Error terminal: `magnet_error`, `dead`, `virus`, `error`, `corrupted`, infracción o fallo definitivo equivalente | No | Borrar el temporal cuando exista |
| `RD_ERROR` | Error no clasificado como temporal durante la comprobación | No | Borrar el temporal y registrar el motivo |
| `RD_ERROR_TEMPORAL` | 429/34, 502, 503, 504, timeout, reset, Cloudflare o límite activo agotado | No concluyente | Separar de los muertos; borrar el temporal de prueba si existe |
| `RD_API_OFF` | `instantAvailability` no está disponible y la verificación alternativa está desactivada | No | No consultar caché; con la configuración actual no suele quedar así porque se usa `addMagnet` |
| `SIN_TOKEN` | No existe token RD | No comprobado | No llamar a RD |
| `RD_TOKEN_ERROR` | Token rechazado o healthcheck fallido | No comprobado | Abortar comprobaciones RD del lote |
| `SIN_HASH` | No se pudo obtener el infohash | No comprobable como magnet | No llamar a `instantAvailability` |
| `SIN_MAGNET` | La rama esperaba magnet y no lo recibió | No | Terminar esa comprobación |
| `SIN_TORRENT` | La rama esperaba URL `.torrent` y no la recibió | No | Terminar esa comprobación |
| `TORRENT_NO_VALIDO` | El contenido `.torrent` no supera la validación previa | No | No enviarlo a RD |
| `NO_VERIFICADO` | Quedó fuera del límite de candidatos | Desconocido | No llamarlo muerto ni válido |
| `RESCATE_NO_VERIFICADO` | Candidato dudoso no usado por la política de rescate | Desconocido | Mantenerlo fuera de los positivos RD |
| `DIRECT_OK` | Enlace directo comprobado fuera de la lógica torrent RD | Fuera de este contrato | No tratarlo como prueba de caché RD |

### 5.1 Descarte rápido

Sin enlaces presentes, se elimina inmediatamente un temporal cuando RD indica:

- `magnet_error`;
- `dead`;
- `virus`;
- `error`;
- `corrupted`;
- texto `no seeders are available` o equivalente;
- magnet inválido;
- después de seleccionar: progreso 0, sin links y cero seeders o seeders
  desconocidos.

El estado `waiting_files_selection` nunca se considera fallo: activa la lógica
de selección.

## 6. Errores y límites especiales de RD

| Código/respuesta | Interpretación | Comportamiento |
|---|---|---|
| `21` | Límite de torrents activos | Refrescar slots, esperar 1,5 s y reintentar; si se agota, clasificar como error temporal |
| `33` | El mismo torrent ya está activo | No repetir a ciegas; refrescar el índice, localizarlo por hash y reutilizar su ID o sus enlaces si ya está descargado |
| `34` o HTTP `429` | Demasiadas peticiones | Aplicar pacer y cooldown, reintentar hasta 6 veces y conservar como temporal si se agota |
| `35` o HTTP `451` | Archivo bloqueado/infractor | Error terminal `RD_FAIL`, sin reintento |
| `37` | Endpoint desactivado | Desactivar `instantAvailability` en memoria durante 900 s y verificar por `addMagnet` |
| HTTP `502/503/504` | Fallo temporal de servicio | Reintentos temporales y `RD_ERROR_TEMPORAL` si no se recupera |
| HTTP `404` al borrar/comprobar limpieza | El temporal ya no existe | Limpieza resuelta; no es fallo |

### 6.1 Protección contra 429

La protección trabaja en dos capas:

1. Límite global: 235 llamadas por minuto y ráfaga máxima de 4.
2. Regulación por endpoint: intervalo, concurrencia y cooldown independientes.

Un 429 aislado pausa globalmente 3 segundos y el endpoint afectado 6 segundos.
Si se detectan al menos tres grupos de endpoint o cinco errores totales dentro de
20 segundos, el cooldown global pasa a 10 segundos. El intervalo del endpoint
se multiplica por 1,35 hasta un máximo de 2,5 segundos y se recupera de forma
gradual, multiplicando por 0,9 tras 60 segundos sin nuevos 429.

## 7. Configuración efectiva actual

Los siguientes son valores efectivos, después de combinar defaults y
`config.json`. No incluyen credenciales.

### 7.1 Capacidad y candidatos

| Opción | Valor | Efecto |
|---|---:|---|
| `verify_max_candidates` | `60` | Tope del batch magnet con API instantánea desactivada y de la rama `.torrent`; no limita los `RD_INSTANT` cuando el endpoint funciona |
| `rd_verify_queue_enabled` | `true` | Usa la cola coordinada de verificaciones RD |
| `rd_verify_parallel_workers` | `60` | Máximo lógico de workers, limitado por número de candidatos y pacers |
| `verify_wait_attempts` | `1` | Una lectura principal por candidato magnet; el valor está forzado internamente |
| `verify_wait_sec` | `0.25` | Espera entre lecturas de la comprobación magnet |
| `verify_instant_results_with_addmagnet` | `true` | Nunca confiar solo en `instantAvailability` |
| `verify_candidates_when_api_off` | `true` | Si falla el endpoint instantáneo, usar `addMagnet` |
| `torrent_candidate_probe_enabled` | `true` | Materializar y validar candidatos `.torrent` |
| `torrent_candidate_probe_max` | `40` | Máximo de URLs `.torrent` materializadas previamente; las posteriores no quedan bloqueadas por este ajuste |
| `torrent_candidate_probe_timeout_sec` | `12` | Timeout de esa materialización |

### 7.2 Ritmo y concurrencia por endpoint

| Endpoint/grupo | Intervalo mínimo | Concurrencia máxima |
|---|---:|---:|
| `addMagnet` | `1.5 s` | `1` |
| `selectFiles` | `0.75 s` | `1` |
| `delete` | `0.65 s` | `1` |
| `info` | `0.10 s` | `4` |
| `activeCount` | `0.80 s` | `1` |
| lista de torrents | `0.80 s` | `1` |
| otros endpoints | `0.10 s` | `2` |

### 7.3 Reintentos, cachés y slots

| Opción | Valor | Efecto |
|---|---:|---|
| `rd_temp_error_retries` | `2` | Intentos ordinarios ante error temporal |
| `rd_temp_error_retry_sec` | `1.0` | Base del backoff temporal, multiplicador 1,5 |
| `rd_429_retry_attempts` | `6` | Intentos especiales para 429/error 34 |
| `rd_retry_21_wait_sec` | `1.5` | Espera por límite de torrents activos |
| `rd_retry_33_resolve_existing` | `true` | Resolver el torrent ya activo por hash |
| `rd_instant_disabled_cache_ttl_sec` | `900` | Tiempo sin volver a probar el endpoint 37 |
| `rd_active_slots_enabled` | `true` | Coordinar altas con capacidad activa real |
| `rd_active_slots_refresh_sec` | `2.0` | Cadencia normal de refresco de slots |
| `rd_active_slots_wait_sec` | `0.35` | Espera cuando no hay hueco |
| `rd_active_slots_release_on_downloaded` | `true` | Liberar reserva al llegar a descargado |
| `rd_existing_preload_enabled` | `true` | Precargar torrents existentes |
| `rd_existing_index_by_hash` | `true` | Resolver duplicados y reutilizables por hash |
| `rd_existing_info_cache_enabled` | `true` | Evitar lecturas repetidas de `info` |
| `rd_existing_torrents_limit` | `1000` | Máximo de existentes inspeccionados |
| `rd_existing_active_limit_on_33` | `500` | Alcance del refresco al resolver error 33 |

### 7.4 Descarte y limpieza

| Opción | Valor | Efecto |
|---|---:|---|
| `rd_fast_discard_enabled` | `true` | Activa descarte temprano seguro |
| `rd_fast_discard_message_match_enabled` | `true` | Interpreta mensajes terminales de RD |
| `rd_fast_discard_zero_progress_enabled` | `true` | Descarta post-selección sin progreso ni seeders |
| `rd_fast_discard_dead_status_enabled` | `true` | Descarta estados muertos explícitos |
| `cleanup_failed_verifications` | `true` | Borra temporales fallidos |
| `cleanup_unselected_verified` | `true` | Borra positivos temporales no elegidos |
| `rd_final_cleanup_enabled` | `true` | Ejecuta barrido final aunque haya fallos o cancelación |
| `rd_final_cleanup_attempts` | `3` | Intentos del barrido final |
| `rd_final_cleanup_wait_sec` | `1.5` | Pausa entre intentos finales |
| `rd_cleanup_final_skip_already_deleted` | `true` | No repetir borrados ya confirmados |
| `rd_delete_retry_attempts` | `5` | Intentos específicos de borrado |
| `rd_delete_retry_base_sec` | `0.8` | Base del backoff de borrado |
| `rd_delete_retry_max_sec` | `4.0` | Tope del backoff de borrado |
| `rd_post_select_extra_poll_enabled` | `true` | Lectura rápida adicional tras seleccionar |
| `rd_post_select_poll_sec` | `0.25` | Espera antes de esa lectura |

### 7.5 Rescate de candidatos dudosos

| Opción | Valor | Efecto |
|---|---:|---|
| `rd_rescue_enabled` | `true` | Permite una segunda comprobación de candidatos con duda razonable |
| `rd_rescue_max_candidates` | `5` | Máximo del rescate |
| `rd_rescue_only_if_no_rd_ok` | `true` | Solo rescatar si aún no existe ningún positivo RD |
| `rd_rescue_min_title_ratio` | `0.5` | Coincidencia mínima para entrar en rescate |

## 8. Configuración heredada sin efecto en la selección actual

El `config.json` contiene estas opciones:

```text
pack_auto_select_best_file=true
pack_hard_skip_without_match=true
pack_min_video_gb=0.3
pack_only_video_files=true
pack_query_match_min_ratio=0.55
video_extensions=[.mkv,.mp4,.avi,.m4v,.mov,.wmv]
```

Las cinco opciones `pack_*` no son consultadas por el motor efectivo actual y
no cambian la decisión de `selectFiles`. No deben presentarse como controles
activos ni copiarse a otro proyecto esperando selección automática.

`video_extensions` sí se usa para clasificar archivos en la instantánea
diagnóstica. Además, el código añade siempre `.m2ts`, `.ts`, `.webm`, `.mpg` y
`.mpeg`. Esa clasificación no evita que se seleccionen archivos no multimedia,
porque la orden efectiva sigue siendo `files=all`.

## 9. Qué sucede al iniciar la descarga de un positivo RD

Esta es únicamente la frontera de salida de RD, no el flujo del proyecto:

1. Se vuelve a validar la evidencia; una tarjeta antigua no basta.
2. Si el hash ya existe en RDT-Client y está realmente listo, no se duplica.
3. Si el registro RDT anterior está bloqueado o en error, se elimina antes de
   reintentar; si está pendiente pero no es seguro tocarlo, se rechaza la nueva
   alta para evitar duplicados.
4. Para un positivo creado por la prueba se hace un preflight nuevo en RD con
   `addMagnet` o `addTorrent` y `selectFiles`.
5. El preflight se mantiene vivo mientras el magnet o `.torrent` se entrega a
   RDT-Client.
6. Un seguimiento en segundo plano espera a que RDT quede preparado o listo.
7. Cuando RDT queda listo, se borra el torrent temporal de preflight en RD.
8. Si la entrega o el seguimiento falla o vence, también se solicita la limpieza
   del preflight; nunca debe abandonarse intencionadamente como residuo.

Un torrent RD ya existente y descargado usa evidencia reutilizable: se refresca
antes de la entrega, pero no se borra de la cuenta RD como si fuera un temporal.

Si RD devuelve un resultado no válido, este contrato termina ahí. Cualquier
estrategia externa alternativa pertenece a otro componente y no forma parte de
esta configuración RD.

## 10. Cancelación y limpieza efectiva

La cancelación se comprueba antes y durante llamadas, esperas y workers. Cuando
se cancela:

1. no se envían nuevos candidatos;
2. el temporal actual se marca como fallido;
3. se entra en una sección de limpieza no cancelable;
4. se intenta borrar el temporal;
5. el barrido final revisa los IDs temporales o fallidos, pero excluye los
   positivos del lote y los existentes reconocidos;
6. confirma la desaparición mediante `404` o registra explícitamente cualquier
   resto que no pudo eliminar.

La limpieza final reúne IDs temporales, fallidos y borrados pendientes. Los
positivos se delegan a la limpieza posterior de `shown`. Por ello, una
cancelación después de crear un `RD_OK` pero antes de construir `shown`, o un
positivo que quede fuera del límite visible, puede dejar un temporal. Los
fallos de borrado se registran; la desaparición absoluta no se puede prometer.

## 11. Contrato mínimo para reproducir esta lógica

Otro proyecto que quiera copiar exactamente este comportamiento debe cumplir:

1. No declarar éxito por `instantAvailability`; confirmar con alta real e
   inspección de `info`.
2. No declarar éxito por recibir un ID; exigir links y estado/progreso útil.
3. Tratar `waiting_files_selection` como una transición normal y enviar
   `files=all`, salvo IDs explícitos aportados por el contrato.
4. Resolver duplicados por hash antes de crear nuevas entradas.
5. Separar fallos terminales, ausencia de caché, falta de comprobación y errores
   temporales.
6. Regular cada endpoint y reaccionar de forma adaptativa a 429.
7. Intentar borrar temporales fallidos y positivos mostrados no elegidos,
   registrando cualquier resto; el código actual no cubre todos los positivos
   creados antes de una cancelación ni los que quedan fuera de `shown`.
8. No borrar existentes descargados marcados `rd_existing=true`; los activos
   recuperados por error 33 no tienen hoy esa misma protección.
9. Volver a comprobar RD justo antes de entregar un positivo a un gestor de
   descargas.
10. Mantener el preflight hasta que el receptor confirme que ya puede continuar
    y borrarlo después.

Esa combinación, junto con las limitaciones expresas de este documento, define
el comportamiento funcional vigente. No debe elevarse ninguna de sus limpiezas
best-effort a garantía absoluta.

## 12. Fuentes y validación de vigencia

La fuente principal del motor RD es
`app/motor/btdigg/rd_turbo_pro.py`, con reintentos auxiliares en
`app/motor/btdigg/_motor_rd_retry.py`. El preflight de descarga y la limpieza
posterior viven en `app/api/btdigg_rd/send.py` y
`app/api/btdigg_rd/_rd_client.py`.

Después de cualquier cambio funcional se deben contrastar defaults más
`config.json`, contratos RD, pruebas de selección `files=all`, reintentos,
errores especiales y la caja negra reciente. Las credenciales y el runtime
crudo no forman parte de esta especificación.

# Flujo técnico completo de búsqueda y descarga BTDigg + RD + qBittorrent

## 1. Objetivo de este documento

Este documento describe la mecánica completa del sistema de búsqueda y
descarga: qué recibe, qué ejecuta, cómo obtiene candidatos, cómo los normaliza,
qué descarta, qué rescata, cómo los ordena, cuándo consulta Real-Debrid, cuándo
prueba qBittorrent, qué enseña, qué conserva y cómo decide la ruta final de una
descarga.

Está escrito como especificación de reconstrucción. Un proyecto distinto puede
usar este documento para reproducir el comportamiento funcional sin copiar la
interfaz ni la estructura exacta de Buscador RD.

La configuración interna detallada del servidor Real-Debrid, sus límites,
reintentos, selección `files=all`, errores especiales y limpieza está en el
documento complementario
[`configuracion-servidor-rd.md`](configuracion-servidor-rd.md). Aquí se explica
cuándo entra RD en el flujo, qué recibe y cómo su respuesta altera las
decisiones generales.

Este texto documenta el comportamiento efectivo del código y la configuración
viva observada el 10 de julio de 2026. Cuando un comentario antiguo contradice
al código ejecutado, manda el código.

## 2. Qué abarca y qué no abarca

Incluye:

- búsqueda individual desde la web;
- lista de búsquedas secuenciales;
- modos `0`, `1` y `3`;
- páginas y búsqueda adicional de calidad;
- obtención y extracción de magnets;
- normalización, hash, tamaño, deduplicación y contexto;
- scoring, palabras buenas/malas y filtros de calidad/idioma;
- criba estricta por coincidencia en un mismo título o archivo;
- rescate controlado de coincidencias dudosas;
- comprobación RD;
- prueba qBittorrent opcional;
- composición, orden y ocultación de resultados;
- jobs, streaming, cancelación y recuperación tras recarga;
- artefactos, historial y caja negra;
- validación del clic de descarga;
- decisión RD/RDT-Client/qBittorrent;
- duplicados, destinos, selección final, seguimiento y limpieza.

No desarrolla la transcripción por voz, Cloudflared, Whisper, el botón Push ni
el resolver de títulos. Esas funciones pueden alimentar o acompañar la web,
pero no cambian el embudo BTDigg/RD/qB descrito aquí.

## 3. Resumen ejecutivo del comportamiento

```text
Consulta + páginas + modo + GB mínimo + qB ON/OFF
                         |
                         v
                Crear job exclusivo
                         |
                         v
              Buscar páginas en BTDigg
                         |
                         v
        Extraer magnets, hash, título, contexto y tamaño
                         |
                         v
          Deduplicar por hash/magnet/enlace fuente
                         |
                         v
      Puntuar según modo y eliminar lo incompatible
                         |
                         v
 Criba: todos los términos juntos en título o mismo archivo
                 /                    \
           principal                rescate/desecho
               |                         |
               +-----------+-------------+
                           v
             Filtro aproximado de tamaño
                           |
                           v
            Real-Debrid: confirmar de verdad
                           |
          +----------------+----------------+
          |                                 |
       RD válido                      no válido/no concluyente
          |                                 |
          |                     qB activado: prueba temporal
          |                                 |
          +----------------+----------------+
                           v
           Ocultar muertos y ordenar resultados
                           |
                           v
        Promover artefactos, guardar historial y mostrar
                           |
                           v
         Usuario pulsa la acción de una tarjeta vigente
                           |
                           v
     Validar índice/hash/enlace contra la verdad del servidor
                           |
                           v
        Elegir RD/RDT-Client o qB según evidencias reales
                           |
                           v
      Evitar duplicados, registrar y seguir hasta entrega
```

El principio central es separar tres conceptos que no deben confundirse:

1. **Encontrado:** BTDigg devolvió un magnet o enlace.
2. **Comprobado:** RD o qB aportó evidencia técnica de que es utilizable.
3. **Entregado:** al pulsar descargar, el servidor volvió a validar la tarjeta y
   el receptor final aceptó la descarga o ya la tenía.

Una fila encontrada no tiene derecho automático a llegar a la pantalla, y una
fila que llegó a la pantalla no se envía sin volver a comprobar su contrato.

## 4. Componentes y responsabilidades

### 4.1 Web y API

La web recoge los parámetros, crea el job, muestra actividad, recibe resultados
y envía la selección final. No ejecuta por sí misma la lógica de scoring ni
decide si una fila es RD/qB válida.

Entradas principales:

| Acción | Endpoint | Responsabilidad |
|---|---|---|
| Iniciar búsqueda | `POST /api/job` | Validar exclusión mutua y crear job |
| Estado puntual | `GET /api/job/{id}` | Devolver snapshot del job |
| Actividad en vivo | `GET /api/job/{id}/stream` | SSE de logs, estados y resultado final |
| Cancelar | `POST /api/job/{id}/cancel` | Marcar cancelación cooperativa |
| Resultado vigente | `GET /api/results/btdigg` | Cargar artefactos promovidos y sanearlos |
| Enviar descarga | `POST /api/rdt/send` | Revalidar tarjeta y decidir ruta final |
| qB de la próxima búsqueda | `GET/POST /api/qbit-toggle` | Leer o persistir `qbit_probe_enabled` |
| Historial normal | `GET /api/history/btdigg` | Recuperar búsquedas terminadas |
| Historial sin semillas | `GET /api/history/qbit-no-seeds` | Recuperar pruebas qB sin vida |
| Cola | `/api/search-queue` | Ejecutar elementos de uno en uno |

### 4.2 Supervisor de jobs

El supervisor crea un runtime aislado, lanza el motor en un subproceso, recoge
la salida, actualiza estados y decide si los artefactos se pueden publicar como
últimos resultados válidos.

### 4.3 Editor maestro

`rd_turbo_editor_maestro.py` es el puente limpio. En una búsqueda web ejecuta:

```text
python -u rd_turbo_editor_maestro.py
  --search
  --query <consulta>
  --pages <páginas>
  --mode <0|1|3>
  --min-gb <mínimo>
```

Este puente fija las variables globales de consulta y tamaño, llama al motor,
guarda únicamente el TOP mostrado y limpia los torrents RD temporales de la
búsqueda antes de terminar.

### 4.4 Motor

`rd_turbo_pro.py` realiza búsqueda, extracción, scoring, criba, RD, qB,
ordenación y exportación. Los ayudantes `_motor_rd_retry.py`,
`_motor_qbt_probe.py` y `_motor_exports.py` encapsulan reintentos RD, prueba qB y
artefactos, pero pertenecen al mismo contrato funcional.

### 4.5 Capa de entrega

`send.py` y sus módulos auxiliares no vuelven a buscar. Reciben una tarjeta,
comprueban que sigue existiendo en los resultados o historial del servidor,
construyen un contrato fiable y escogen la ruta final.

## 5. Entradas de una búsqueda

### 5.1 Campos

| Campo | Significado | Regla efectiva |
|---|---|---|
| `query` | Título o texto buscado | Se recorta; vacío hace fallar el motor con código 2 |
| `pages` | Rango BTDigg | Vacío usa `default_pages`; actual `1-3` |
| `mode` | Política de calidad/idioma | Solo `0`, `1` o `3`; cualquier otro pasa a `0` |
| `min_gb` | Mínimo aproximado | Vacío usa `min_size_gb`; actual `0` |
| qB toggle | Probar alternativas qB | Se guarda en configuración antes del job; no viaja en el payload normal |

La web guarda el formulario localmente y también en el estado compartido. Una
recarga vuelve a consulta, páginas, modo y mínimo anteriores siempre que exista
estado guardado. Los defaults solo rellenan un formulario que todavía no tiene
estado del usuario.

### 5.2 Semántica de páginas

La cadena de páginas se convierte así:

| Entrada | Páginas reales |
|---|---|
| `1` | página 1 |
| `3` | páginas 1, 2 y 3 |
| `1-5` | páginas 1 a 5 |
| `5-2` | se corrige a páginas 2 a 5 |
| `0` | páginas 1 a `safe_max_pages_when_zero`, actualmente 30 |
| inválida | vuelve a `default_pages`, actualmente `1-3` |

Un rango nunca empieza por debajo de 1 ni supera 500 en su extremo final. El
valor `0` no significa infinito: siempre respeta el tope de seguridad.

### 5.3 Estado qB

El botón `qB ON/OFF` escribe inmediatamente `qbit_probe_enabled` en el
`config.json` vivo. Es un estado global del servicio, compartido entre clientes,
y afecta a la siguiente búsqueda que cargue la configuración.

En la instantánea actual:

```text
qbit_probe_enabled=false
```

Por tanto, una búsqueda normal ejecutada ahora trabaja solo con RD y registra
`qbt_probe_skipped`. El documento también describe íntegramente la rama qB para
cuando se active el botón o un elemento de cola tenga qB ON.

## 6. Exclusión mutua y creación del job

### 6.1 Solo un trabajo de motor

Los estados activos son:

```text
queued
running
cancelling
```

Antes de aceptar `POST /api/job`, el servidor comprueba:

1. que el módulo sea `btdigg` y la acción `search`;
2. que la cola de búsquedas no esté trabajando;
3. que no exista otro job normal o prueba RD activa.

Si ya existe uno, responde HTTP 409 con su identificador. La web no crea un
duplicado: intenta reconectarse al job existente.

### 6.2 Identidad y estado inicial

El job normal recibe un ID hexadecimal corto de 12 caracteres y empieza:

```text
kind=job
module=btdigg
action=search
status=queued
cancel_requested=false
```

Antes de crearlo se sincroniza el token RD desde la fuente del servicio hacia
el fichero esperado por el motor, pero nunca se imprime ni se incorpora a los
artefactos públicos.

### 6.3 Runtime aislado

Cada job tiene su propia carpeta bajo `data/jobs/{job_id}/`:

```text
cancel.json
safeout.log
shown.json
exports/
last_links.txt
last_links_ordenado.txt
```

Esto impide que una búsqueda a medias sobrescriba los últimos resultados buenos.
Solo un job terminado con código 0 promociona sus artefactos al runtime compartido.

La retención normal conserva al menos los últimos 100 jobs y también los jobs de
los últimos 7 días. La limpieza se ejecuta antes de iniciar uno nuevo.

## 7. Ejecución y comunicación en vivo

### 7.1 Subproceso

El supervisor arranca Python sin buffer, fija las rutas aisladas mediante
variables de entorno y conecta stdout más el `safeout.log` a la memoria del job.
El log público en memoria se limita a las 600 últimas líneas.

Los estados avanzan normalmente:

```text
queued -> running -> done
```

o bien:

```text
queued/running -> cancelling -> cancelled
queued/running -> error
```

### 7.2 SSE y fallback

La web abre `EventSource` contra `/api/job/{id}/stream`. El stream emite:

- `log`: una línea nueva;
- `status`: cambio de estado;
- `done`: resultados y metadatos terminales;
- comentario ping cada 15 segundos.

Si en 2,5 segundos no llega ninguna línea LIVE, si el navegador no soporta SSE
o si el stream falla, la web pasa a polling de `GET /api/job/{id}` cada segundo.
Ambas rutas terminan en el mismo snapshot; el fallback no cambia el motor.

### 7.3 Recarga y reconexión

El identificador activo se guarda en `localStorage`. Al iniciar, volver de
background o recibir `pageshow`, la web:

1. consulta estado compartido y qB;
2. intenta recuperar el ID local;
3. consulta `/api/job/active` si el ID local ya no sirve;
4. se reconecta al stream o polling;
5. solo carga resultados estáticos si no existe trabajo activo.

Además realiza un refresco compartido cada 15 segundos y evita recargar la tabla
de resultados más de una vez cada 30 segundos cuando no hay trabajo.

## 8. Búsqueda real en BTDigg

### 8.1 Normalización de la consulta

La consulta se pasa a minúsculas ASCII, se eliminan acentos y se sustituyen los
separadores por espacios. Por ejemplo:

```text
El Señor de los Anillos: 2001
-> el senor de los anillos 2001
```

Esta forma se URL-codifica para BTDigg. La consulta original sigue disponible
para logs y presentación.

### 8.2 Obtención de cada página

La vía normal por página es:

1. construir `https://en.btdig.com/search?q={consulta}&p={pagina-1}`;
2. intentar HTTP con `curl_cffi` imitando sucesivamente Chrome 124, 120 y 110;
3. aceptar el HTML si no parece 429, CAPTCHA, bloqueo, certificado, base de datos
   caída o acceso prohibido;
4. si esa vía falla, ejecutar Chromium headless con `--dump-dom`;
5. alimentar siempre el mismo extractor de magnets.

El timeout actual de `curl_cffi` es 25 segundos y el del rescate DOM es 45
segundos. Entre páginas se esperan 2 segundos en el navegador automático. La
opción `delay_between_btdigg_pages_sec=3` pertenece a la vía HTTP directa
histórica; la búsqueda web actual usa `browser_delay_between_pages_sec=2`.

### 8.3 Corte temprano

La búsqueda se detiene cuando encuentra dos páginas consecutivas sin magnets.
Una página con resultados pone a cero el contador de vacías. Esto evita recorrer
el rango completo cuando BTDigg ya no devuelve material.

### 8.4 Búsqueda adicional de calidad

En modo `1` (calidad pura), si la consulta no contiene ya `2160p`, `4k`, `uhd`
o equivalente, se lanza una segunda consulta:

```text
<consulta original> 2160p
```

La consulta adicional usa actualmente una página. Sus resultados se mezclan y
se deduplican con los de la búsqueda base.

No hay rescate adicional de calidad en modo `0` ni en modo `3`. En modo `3` se
prefiere no abrir la búsqueda con términos extra porque el idioma obligatorio
ya es el criterio dominante.

## 9. Extracción y representación de candidatos

### 9.1 Detección del magnet

El extractor reconoce:

- `magnet:?xt=urn:btih:...` normal;
- magnet dentro de `href` HTML;
- magnet URL-encoded (`magnet%3A%3F...`);
- hash SHA-1 hexadecimal de 40 caracteres;
- hash Base32 de 32 caracteres, convertido a hexadecimal cuando es posible.

Un magnet sin BTIH válido se ignora.

### 9.2 Contexto asociado

Para cada magnet se conserva una ventana amplia alrededor del enlace. De ella se
derivan:

- título `dn` del magnet, texto del enlace o título inferido;
- tamaño más grande detectado;
- posibles archivos internos de vídeo o `.torrent`;
- coincidencia de los términos buscados;
- texto bruto limitado para auditoría.

El extractor de tamaño comprende TB/TiB, GB/GiB y MB/MiB y normaliza todo a
GiB. Solo admite valores aproximados entre 0,001 y 5000 GiB para evitar falsos
positivos evidentes.

### 9.3 Modelo interno

Cada candidato mantiene, entre otros:

```text
title, magnet, torrent_url, hash, source_url
size_gb, btdigg_file_name, btdigg_file_size_gb
same_file_match, same_file_reason
score, reason, prefilter_bucket, prefilter_reason
rd_status, rd_existing, rd_links, rd_torrent_id
selected_file_ids, selected_file_name, selected_file_size_gb
qbt_status, qbt_reason, qbt_seeds, qbt_peers
qbt_progress, qbt_speed_bps, qbt_size_gb, qbt_was_existing
```

No todos los campos significan lo mismo: `size_gb` puede ser el tamaño bruto
inferido, mientras que `selected_file_size_gb` es evidencia más concreta y tiene
prioridad al filtrar y mostrar.

### 9.4 Deduplicación

La clave de identidad se toma en este orden:

```text
hash -> magnet -> torrent_url -> source_url
```

Se conserva la primera aparición de cada clave. Los duplicados de páginas base,
rescates de calidad o fuentes repetidas no gastan otra comprobación RD/qB.

## 10. Scoring por modo

### 10.1 Normalización lingüística

Las comparaciones:

- pasan a minúsculas;
- eliminan acentos;
- trabajan con límites de palabra;
- evitan que términos cortos como `ts`, `cam` o `esp` coincidan dentro de otra
  palabra no relacionada;
- admiten frases equivalentes sin separadores mediante una forma compacta.

### 10.2 Palabras de mala calidad

Cada coincidencia resta 70 puntos:

```text
cam, camrip, ts, telesync, screener, hdcam, hdts, workprint,
telecine, hdtc, dvdscr, dvdscreener, bdscr, webscr, webscreener,
pdvd, predvdrip, pre-dvd
```

### 10.3 Modo 0: sin filtro

El modo `0` no exige calidad ni idioma:

- parte de 0;
- resta 70 por cada palabra mala;
- no elimina por el umbral de puntuación;
- ordena por score, sin usar tamaño como desempate del scoring inicial.

“Sin filtro” no significa “sin seguridad”. Después siguen aplicándose la criba
de coincidencia, tamaño si el usuario lo pidió, comprobación RD/qB, ocultación
de muertos y validación final de descarga.

### 10.4 Modo 1: calidad pura

Reglas exactas:

1. cualquier palabra mala produce score `-999`;
2. debe aparecer `2160p`, `4k`, `uhd`, `ultra hd` o `ultrahd` en el título,
   archivo reconocido o archivo interno coincidente;
3. sin marca 4K produce score `-999`;
4. una marca válida suma 35;
5. si hay tamaño dentro del rango general, suma
   `min(20, floor(size_gb / 3))`;
6. un tamaño conocido fuera del rango general resta 35.

Después se eliminan los candidatos con score menor o igual a `-500`. En la
práctica desaparecen los no 4K y los marcados como basura.

### 10.5 Modo 3: castellano obligatorio

Palabras positivas activas:

```text
castellano, castilian, espanol, spanish, esp, es-en, cast, spa
```

Palabras negativas de idioma:

```text
latino, latin, vose, subtitulado
```

Reglas exactas:

1. encontrar una palabra positiva suma 40;
2. no encontrar ninguna resta 999;
3. encontrar una negativa resta otros 40;
4. con idioma positivo y tamaño normal suma
   `min(15, floor(size_gb / 4))`;
5. tamaño conocido fuera del rango resta 35;
6. cada palabra mala de calidad resta 70.

También aquí se exige score mayor que `-500`, por lo que un resultado sin señal
de castellano queda fuera aunque sea técnicamente descargable.

## 11. Criba de identidad: el título debe coincidir de verdad

### 11.1 Por qué existe

BTDigg puede devolver packs o bloques donde las palabras buscadas aparecen
repartidas entre archivos distintos. El sistema no acepta que una palabra esté
en un episodio, otra en un extra y otra en el título general: debe existir una
coincidencia coherente en un único título o archivo.

### 11.2 Términos buscados

Todos los tokens alfanuméricos normalizados de la consulta entran en la
comparación. No hay una lista de stopwords. Un año como `2001` también es un
término. Si un nombre interno contiene un rango de años, el año se considera
cubierto cuando cae dentro del rango.

### 11.3 Regla de coincidencia

El candidato pasa directamente si:

- todos los términos aparecen en el título del torrent; o
- aparecen juntos en un mismo archivo de vídeo detectado dentro del contexto.

La coincidencia interna mínima usa actualmente el mismo umbral que qB:

```text
qbit_same_file_min_ratio=0.9
```

Es decir, se exige el 90 % de términos en el mismo archivo, salvo que el título
general ya cubra el 100 %.

### 11.4 Tres carriles

Cada resultado entra en un bucket:

| Bucket | Condición | Acción |
|---|---|---|
| `primary` | Coincidencia completa y coherente | Sigue al filtro de tamaño y RD |
| `rescue` | Archivo interno coincide pero el título no, o título parcial fuerte | Se reserva para un rescate RD limitado |
| `discard` | No existe coincidencia suficiente en un mismo título/archivo | No gasta RD ni qB normal; queda solo en export diagnóstico si está activado |

Un archivo interno coincidente sin palabras coincidentes en el título general
no se trata como principal: entra en rescate. Esto protege contra packs con
nombres generales engañosos.

### 11.5 Rescate parcial

Si el título contiene términos de la consulta con ratio igual o superior a
`rd_rescue_min_title_ratio=0.5`, el resultado no se tira todavía. Se marca
`RESCATE_BUSQUEDA`.

El rescate se ejecuta después de la primera ronda RD y cumple:

```text
rd_rescue_enabled=true
rd_rescue_only_if_no_rd_ok=true
rd_rescue_max_candidates=5
rd_rescue_min_title_ratio=0.5
```

Por tanto:

1. si la ronda principal ya obtuvo al menos un RD válido, no se gasta RD en el
   rescate;
2. si no obtuvo ninguno, se ordenan los rescatables y se comprueban como máximo
   cinco;
3. los no comprobados quedan `RESCATE_NO_VERIFICADO`, no “muertos”.

## 12. Filtro de tamaño solicitado

### 12.1 No es un corte rígido exacto

El mínimo introducido por el usuario admite tolerancia para tamaños publicados
de forma aproximada:

```text
tolerancia = max(1 GiB, 5 % del mínimo solicitado)
tolerancia máxima = 3 GiB
mínimo efectivo = mínimo solicitado - tolerancia
```

Ejemplo: pedir 20 GiB acepta desde 19 GiB; pedir 100 GiB acepta desde 97 GiB.

### 12.2 Orden de fuentes de tamaño

La primera medida disponible se toma en este orden:

```text
selected_file_size_gb
btdigg_file_size_gb
size_gb
rd_largest_gb
qbt_size_gb
```

Antes de RD se puede conservar un candidato si el tamaño total satisface el
mínimo, el archivo individual parece pequeño y el título coincide de forma
completa. Después de RD se prioriza el tamaño del archivo seleccionado o el
mayor tamaño confirmado por RD.

### 12.3 Tamaño desconocido

Un resultado sin tamaño no se descarta automáticamente. Se conserva con una
nota `sin_tamano_para_min_*` para que RD/qB pueda aportar una medida real. Esto
evita perder un torrent bueno solo porque BTDigg no publicó tamaño.

### 12.4 Doble aplicación

El filtro se aplica:

1. antes de RD, con la evidencia de BTDigg;
2. después de RD, con la evidencia interna mejorada;
3. también antes y después del rescate.

Si un temporal RD termina siendo demasiado pequeño, se borra con motivo
`descartado_por_tamano` o `rescate_descartado_por_tamano`.

En la configuración viva `min_size_gb=0` y el formulario actual puede dejarlo
vacío, por lo que esta fase solo corta cuando el usuario pide expresamente un
mínimo.

## 13. Preparación y orden antes de Real-Debrid

La secuencia exacta es:

1. puntuar todos los resultados;
2. en modos `1` y `3`, quitar score `<= -500`;
3. ejecutar la criba de identidad;
4. separar principales, rescatables y descartados;
5. aplicar tamaño a los principales;
6. ordenar antes de RD.

Orden previo:

- modo `0`: score descendente;
- modos `1` y `3`: score descendente y, a igualdad, tamaño efectivo
  descendente.

La finalidad es gastar las llamadas RD limitadas en los candidatos más
prometedores. El orden de BTDigg por sí solo no decide qué se verifica primero.

## 14. Fase Real-Debrid dentro del embudo

### 14.1 Entradas que recibe

RD recibe los candidatos principales que sobrevivieron a modo, identidad,
deduplicación y tamaño. Los enlaces directos ajenos a torrent se validan por su
propia rama y no se confunden con magnets.

Antes de consultar RD:

- debe existir token y superar healthcheck;
- las URLs `.torrent` se materializan y se comprueba que sean metainfo real;
- los magnets deben tener hash;
- se limita la verificación seria a 60 candidatos.

### 14.2 Decisión

La consulta rápida `instantAvailability` no basta. Con la configuración actual,
un positivo se confirma mediante alta real, lectura de `info`, selección de
archivos y presencia de links.

Salidas relevantes para el resto del flujo:

| Estado RD | Interpretación general |
|---|---|
| `RD_OK` | Evidencia utilizable confirmada |
| `RD_INSTANT` | Positivo provisional; normalmente se transforma al verificar |
| `NO_CACHE` | Hash no presente en caché instantánea |
| `NO_INSTANT` | RD no produjo links útiles a tiempo |
| `RD_FAIL` | Rechazo terminal |
| `RD_ERROR_TEMPORAL` | Fallo no concluyente; no se llama muerto |
| `RD_ERROR` | Error no temporal de la comprobación |
| `NO_VERIFICADO` | Fuera del límite; estado desconocido |

Los detalles de cada endpoint, error 21/33/34/35/37, 429, slots, selección
`all`, packs y limpieza están en el documento RD complementario.

### 14.3 Rescate RD

Tras la ronda principal se evalúa el carril `rescue`. Solo se lanza si la
política configurada lo permite. Los positivos rescatados se incorporan al mismo
conjunto central; no forman una tabla separada.

### 14.4 Temporales al acabar la búsqueda

La comprobación puede crear torrents temporales en la cuenta RD. El motor limpia
fallos durante la propia verificación y hace un barrido final. Después, el editor
web ejecuta además:

```text
cleanup_unselected_verified(shown, [], token)
```

Como la selección está vacía durante una búsqueda web, se borran también los
positivos temporales recién verificados que no eran torrents ya existentes.
Esto es intencionado: la búsqueda termina sin dejar pruebas en RD.

La tarjeta conserva la evidencia (`rd_status`, `rd_links`, hash, archivo), pero
el clic final no presupone que aquel ID temporal siga vivo; hace una comprobación
nueva antes de entregar.

## 15. Fase qBittorrent opcional

### 15.1 Cuándo se ejecuta

qB se ejecuta después de RD y del posible rescate. Si
`qbit_probe_enabled=false`, termina inmediatamente con evento
`qbt_probe_skipped` y no abre sesión qB.

Con qB activado y `qbit_probe_only_non_rd_working=true`, solo se prueban
candidatos que no tienen un estado RD utilizable. Así qB actúa como segunda vía,
no como una repetición de los positivos RD.

### 15.2 Criba previa qB

Con `qbit_require_same_file_match=true`, el título o un mismo archivo interno
debe alcanzar la coincidencia configurada del 90 %. Si no:

```text
qbt_status=QBT_NO_COINCIDE_ARCHIVO
```

y no se añade el magnet a qB. Esto evita consumir probes con palabras repartidas
entre distintos archivos de un pack.

### 15.3 Límites actuales

```text
qbit_probe_max_candidates=40
qbit_probe_parallel_workers=5
qbit_probe_wait_sec=35
qbit_probe_poll_sec=2
qbit_probe_save_path=/data/downloads/torrents/incomplete/rd_turbo_probe
qbit_probe_category=manual
qbit_delete_probe_after=true
qbit_show_metadata_only=false
```

Se toman como máximo los primeros 40 candidatos relevantes conservando el orden
producido por las fases anteriores. Cinco workers pueden probarlos en paralelo.

### 15.4 Login y duplicado

Cada worker paralelo abre y verifica sesión mediante:

```text
POST /api/v2/auth/login
GET  /api/v2/app/version
```

Antes de añadir consulta:

```text
GET /api/v2/torrents/info?hashes={hash}
```

Si ya existe:

- no se crea una prueba nueva;
- se marca `qbt_was_existing=true`;
- se evalúa su estado actual;
- nunca se borra al terminar el probe, porque no fue creado por esta búsqueda.

### 15.5 Alta temporal

Si no existe, se envía el magnet con:

```text
paused=false
autoTMM=false
savepath=<ruta temporal de probe>
category=manual
```

Después se consulta por hash cada 2 segundos hasta 35 segundos o hasta obtener
evidencia viva.

### 15.6 Clasificación qB exacta

| Estado | Condición |
|---|---|
| `QBT_OK` | progreso `>= 0.999`, o tamaño conocido y `amount_left=0` |
| `QBT_VIVO` | velocidad positiva |
| `QBT_VIVO` | al menos un seed conectado |
| `QBT_VIVO` | metadatos y disponibilidad `>= 1.0` |
| `QBT_VIVO` | metadatos y progreso real `> 0` |
| `QBT_TRACKER_HINT` | tracker anuncia completos, pero qB no conectó ni mostró vida real |
| `QBT_METADATA` | tiene metadatos y estado de descarga, pero sin vida clara |
| `QBT_NO_PEERS` | sin evidencia de vida al agotar la espera |
| `QBT_NO_INFO` | nunca apareció información por hash |
| `QBT_SIN_HASH` | no hay hash/magnet comprobable |
| `QBT_ADD_ERROR` | qB rechazó el alta |
| `QBT_OFF` | no se pudo conectar/autenticar |
| `QBT_ERROR` | excepción del worker |

Solo `QBT_OK` y `QBT_VIVO` se consideran utilizables. `QBT_METADATA` también
podría considerarse útil si `qbit_show_metadata_only=true`, pero actualmente es
`false`. Un `QBT_TRACKER_HINT` no se convierte en positivo porque la información
del tracker sin conexión real puede ser engañosa.

### 15.7 Limpieza del probe

Todo torrent creado por la prueba se elimina con:

```text
POST /api/v2/torrents/delete
deleteFiles=true
```

Se elimina tanto tras éxito como tras fallo o cancelación. En cancelación se
entra en una sección no cancelable para intentar garantizar la limpieza. Los
torrents que ya existían antes del probe se conservan.

## 16. Composición de la lista final

### 16.1 Conjunto completo y conjunto visible

El motor mantiene dos vistas:

- `checked_all`: incluye principales, descartados por tamaño y, si está activo,
  descartados por identidad; se usa para diagnóstico/export;
- `checked`: candidatos que pueden llegar al usuario.

Con `strict_query_prefilter_keep_discarded_in_exports=true`, la basura de
identidad queda disponible para auditoría sin contaminar la tabla visible.

### 16.2 Ocultación de muertos

Con `hide_non_working_results=true`, se conservan en pantalla únicamente:

- estados RD utilizables (`RD_OK`, `RD_INSTANT`, `DIRECT_OK`);
- estados qB utilizables (`QBT_OK`, `QBT_VIVO`);
- `QBT_METADATA` solo si se habilitara explícitamente.

`RD_ERROR_TEMPORAL` se exporta en su lista propia, pero no se presenta como
resultado confirmado. Esto evita llamar bueno o muerto a algo que RD no pudo
resolver por una caída temporal.

### 16.3 Orden final del motor

La clave de orden es:

```text
1. tiene RD válido
2. tiene qB válido
3. score
4. tamaño efectivo, salvo en modo 0
```

Los RD válidos quedan delante de los exclusivamente qB; dentro de cada grupo
manda la política del modo.

### 16.4 Límite mostrado

El motor corta el TOP a `max_results_to_show`, actualmente 80. Solo ese TOP se
guarda en `shown.json` para la web.

### 16.5 Segundo orden del servidor web

Al cargar el resultado guardado, la API lo sanea y vuelve a ordenar:

```text
RD primero -> qBit después -> otras fuentes -> tamaño descendente -> título
```

Luego renumera los índices. Por eso el índice de la tarjeta pertenece a la lista
vigente del servidor y no debe asumirse igual al orden bruto del motor.

La web permite ordenar visualmente por título, tamaño, seeds, peers o añadido.
Ese orden visual no cambia el `item.index` de contrato que se envía al backend.

## 17. Artefactos generados y promoción

### 17.1 Artefactos del motor

Con `write_exports=true`, cada job puede producir:

| Archivo | Contenido |
|---|---|
| `shown.json` | TOP exacto que el editor entrega al supervisor |
| `ULTIMOS_RESULTADOS.json` | Datos técnicos completos, incluidos descartes conservados para diagnóstico |
| `ULTIMO_TOP.txt` | Representación humana del TOP |
| `ULTIMO_QBIT_VIVOS.txt` | Positivos qB que no son positivos RD |
| `ULTIMO_RD_TEMPORAL.txt` | Errores RD temporales, explícitamente no confirmados |
| `last_links.txt` | Enlaces finales de la vía interactiva antigua, si se generaron |
| `last_links_ordenado.txt` | Enlaces con nombre y orden de selección |

### 17.2 Promoción atómica por éxito

El supervisor solo copia los artefactos del job al runtime compartido cuando el
subproceso termina con código 0. Si termina en error o cancelado:

- no reemplaza los últimos resultados buenos;
- devuelve una lista vacía para ese job;
- conserva la caja negra y runtime aislado para diagnóstico.

Esta regla es importante al replicar el sistema: el resultado compartido debe
ser “último éxito”, no “último intento”.

### 17.3 Historial normal

Tras un job correcto con resultados:

- se guarda consulta, páginas, modo y mínimo;
- se guarda la versión saneada de cada tarjeta;
- se conserva fecha y hora;
- se limita a 30 búsquedas y 30 días;
- se agrupa por día al leerlo.

Una búsqueda correcta sin resultados no crea entrada normal de historial.

### 17.4 Historial qB sin semillas

El supervisor lee `ULTIMOS_RESULTADOS.json`, no solo el TOP visible, y extrae
filas con:

```text
qbt_status=QBT_NO_PEERS
qbt_seeds<=0
```

Las deduplica por hash, magnet, URL, enlace o título y crea un historial
independiente con la misma retención. Así se puede recordar qué se probó y no
tenía vida sin ensuciar la tabla de resultados buenos.

## 18. Fin de la búsqueda en la web

### 18.1 Estado terminal

Al recibir `done` por SSE o polling:

1. se cierra el canal LIVE;
2. `moduleBusy` pasa a falso;
3. se muestra `done`, `error` o `cancelled`;
4. solo con `done` se carga la lista recibida;
5. se invalidan caches de historial;
6. se hace una lectura final del seguimiento RD;
7. se elimina el ID activo local;
8. se reproduce el sonido de finalización una sola vez por job.

Si la cancelación fue forzada o dejó limpieza incierta, la actividad muestra un
aviso para revisar la caja negra.

### 18.2 Tabla visible

Cada fila muestra:

- número visual;
- título;
- tamaño;
- seeds;
- peers;
- antigüedad/fecha;
- acción de descarga;
- copiar enlace;
- resolver título.

La etiqueta de acción se deriva de la fuente/estado, pero es únicamente
presentación. La ruta real se recalcula en el servidor al pulsarla.

En móvil la tabla conserva actualmente un ancho interno de 860 px y se desplaza
horizontalmente dentro del contenedor `.results`, que tiene `overflow:auto`.
El documento debe replicar ese comportamiento si se busca equivalencia visual;
no debe ensanchar el `body` completo.

### 18.3 Persistencia

Se conserva:

- vista principal, ajustes, historial o cola;
- consulta, páginas, modo y mínimo;
- orden de resultados;
- días y búsquedas abiertos del historial;
- borrador de cola;
- paneles colapsados;
- job activo.

El estado existe en local y en un JSON compartido saneado. La versión con marca
de tiempo más reciente evita que una pestaña antigua pise silenciosamente a una
más nueva.

## 19. Contrato seguro al pulsar descargar

### 19.1 El navegador no es fuente de verdad

La web envía:

```text
module, index, title, link, hash, source, status, contract
```

El bloque `contract` del navegador solo es una pista diagnóstica. El servidor
vuelve a cargar los resultados vigentes y reconstruye el contrato desde el campo
`raw` guardado.

### 19.2 Validación de una tarjeta actual

Para una tarjeta de resultados:

1. debe haber resultados vigentes;
2. el índice debe estar dentro del rango;
3. la fila del servidor debe contener magnet o URL real;
4. si cliente y servidor aportan hash, deben coincidir;
5. el hash derivado del enlace del cliente debe coincidir;
6. si el enlace no contiene hash, debe coincidir literalmente con el servidor.

Cualquier divergencia devuelve HTTP 409. Esto bloquea clics antiguos después de
otra búsqueda, índices manipulados y enlaces que no pertenecen a la fila.

### 19.3 Validación desde historial

El historial se valida mediante:

```text
history_kind
history_id
history_result
```

El servidor vuelve a abrir el fichero de historial correspondiente, localiza la
búsqueda y posición y aplica las mismas comparaciones de hash/enlace. Una tarjeta
que ya no existe o no coincide no se envía.

### 19.4 Contrato reconstruido

El contrato fiable contiene:

```text
index, title, hash, link, magnet, torrent_url
rd_status, rd_existing, rd_links, rd_torrent_id
selected_file_name, selected_file_ids
qbt_status, qbt_was_existing, qbt_reason
```

El enlace se normaliza de nuevo. Un magnet debe corresponder al hash esperado;
una URL debe ser la de la fila. Solo después se decide el destino.

## 20. Clasificación del destino

Antes de enviar se clasifica el título como película o serie.

### 20.1 Reglas de serie

Primero se prueban plantillas configurables como:

```text
SXXEXX, SXEX, SXX EXX, XXxXX, XxXX,
Temporada XX, Temp XX, Season XX,
Capitulo XX, Capitulo X, Episode XX, Episodio XX, Cap.XXX
```

Cada `X` representa de uno hasta el número de dígitos de ese bloque. Espacios,
puntos, guiones y guiones bajos se consideran separadores equivalentes.

Después se prueban palabras completas:

```text
capitulo, capítulo, episodio, episode, temporada, temp, season, Cap.XXX
```

Si alguna regla coincide, destino `tv`; en caso contrario, `movies`.

### 20.2 Rutas resultantes

| Destino | RDT-Client | qBittorrent | Inbox `.torrent` |
|---|---|---|---|
| `movies` | `/data/downloads/movies` | `/data/downloads/torrents/complete/movies` | inbox `movies` |
| `tv` | `/data/downloads/tv` | `/data/downloads/torrents/complete/tv` | inbox `tv` |
| `manual` | `/data/downloads/manual` | `/data/downloads/torrents/complete/manual` | inbox `manual` |

La búsqueda no elige el destino definitivo: se calcula otra vez con el título
de la fila validada al pulsar descargar.

## 21. Matriz de decisión de ruta final

La prioridad efectiva es:

| Prioridad | Evidencia | Ruta |
|---:|---|---|
| 1 | `rd_status` reutilizable y `rd_existing=true` | `RD_REUSABLE` hacia RDT-Client |
| 2 | `qbt_status` es `QBT_OK` o `QBT_VIVO` | `QBIT_REUSABLE` hacia qBittorrent |
| 3 | `rd_status` reutilizable, no existente, y `rd_links>0` | `RD_VERIFIED_MAGNET` hacia RDT-Client con preflight nuevo |
| 4 | no hay magnet/URL validado | `BLOCKED_NO_LINK` |
| 5 | existe enlace pero ninguna evidencia reutilizable | `BLOCKED_UNSAFE` |

Estados RD reutilizables para construir contrato:

```text
RD_OK, RD_INSTANT, DIRECT_OK
```

La condición decisiva no es solo el nombre: para un RD no existente se exige
`rd_links>0`. Esto evita enviar una fila que solo heredó una etiqueta.

Normalmente qB solo prueba no-RD y no compite con un positivo RD. Si se cambiara
esa configuración y una fila tuviera a la vez qB vivo y RD válido no existente,
la prioridad de código pondría qB antes que `RD_VERIFIED_MAGNET`.

## 22. Entrega final a qBittorrent

### 22.1 Magnet

Para `QBIT_REUSABLE`:

1. se exige hash válido;
2. se consulta qB por hash;
3. si no se puede comprobar el duplicado, se rechaza con 502;
4. si ya existe cualquier fila con ese hash, se devuelve éxito
   `already_present=true` sin añadir otra;
5. si no existe, se envía el magnet.

Parámetros de alta:

```text
category=<movies|tv|manual>
savepath=<destino qB>
paused=false
stopped=false
contentLayout=Original
autoTMM=false
```

### 22.2 URL `.torrent`

1. se descargan los bytes con timeout de 90 segundos;
2. se exige un mínimo de 40 bytes;
3. se calcula infohash desde el diccionario bencode `info`;
4. se busca duplicado por ese hash;
5. si no existe, se sube multipart a `/api/v2/torrents/add`.

### 22.3 Comprobación conservadora de duplicados

Si el servidor no puede autenticar o consultar qB, no interpreta “no sé” como
“no existe”. Rechaza el alta para evitar duplicados. Si la consulta funciona y
encuentra el hash, no evalúa de nuevo la salud: considera satisfecha la petición
porque la descarga ya está gestionada por qB.

### 22.4 Forzar qB desde historial sin semillas

`force_qbit=true` solo se permite cuando:

```text
from_history=true
history_kind=qbit_no_seeds
```

Fuera de ese historial devuelve 409. La ruta `QBIT_FORCED` reutiliza las mismas
comprobaciones de hash, duplicado y alta; “forzado” no significa inseguro.

## 23. Entrega final a RDT-Client

### 23.1 RD ya existente

Para `RD_REUSABLE` se refresca primero la evidencia:

1. consultar `rd_torrent_id` si existe;
2. exigir estado RD `downloaded` y links;
3. si ese ID ya no sirve, buscar el mismo hash en la lista RD;
4. rechazar con 409 si no se recupera evidencia viva.

Después se comprueba RDT-Client por hash:

- si no se puede comprobar, se rechaza con 502;
- si ya existe y está sano, se devuelve `already_present=true`;
- si falta, se importa magnet o `.torrent`.

El torrent RD existente es contenido legítimo de la cuenta y no se borra como
temporal.

### 23.2 RD verificado durante la búsqueda

La búsqueda web limpió sus temporales, por lo que una fila
`RD_VERIFIED_MAGNET` realiza un preflight final:

1. comprobar duplicado RDT por hash;
2. volver a hacer `addMagnet` o `addTorrent` en RD;
3. seleccionar `selected_file_ids` si el contrato los trae; en otro caso `all`;
4. mantener vivo el ID RD de preflight;
5. subir el magnet o fichero a RDT-Client;
6. localizar la nueva fila RDT por ID/hash;
7. esperar estado preparado;
8. registrar la descarga;
9. iniciar seguimiento en segundo plano;
10. borrar el preflight RD cuando RDT esté realmente encaminado.

Si RDT falla durante el upload, el preflight RD se borra inmediatamente.

### 23.3 Duplicados y salud nativa de RDT

Las fases interpretadas son:

| Fase | Significado | Acción |
|---|---|---|
| `finished` | terminado | reutilizar |
| `healthy_started` | tiene descargas o está descargando | reutilizar |
| `blocked_pending` | aún no añadido a proveedor o esperando selección | eliminar como obsoleto y reintentar |
| `error` | error/fallo | eliminar con datos y reintentar |
| `selected_only` | solo archivos seleccionados | no crear duplicado; rechazar como pendiente no saludable |
| `pending_other` | pendiente ambiguo | no crear duplicado; rechazar |
| `missing` | no existe | crear nueva fila |
| `unknown` | no se pudo comprobar | rechazar por seguridad |

### 23.4 Configuración enviada a RDT-Client

La API nativa recibe:

```text
category=<movies|tv|manual>
hostDownloadAction=0
downloadAction=2 si hay archivo manual; 0 si no
finishedAction=1
finishedActionDelay=0
downloadMinSize=0
includeRegex=""
excludeRegex=""
downloadManualFiles=<selected_file_name o null>
priority=0
torrentRetryAttempts=1
downloadRetryAttempts=3
deleteOnError=0
lifetime=0
downloadClient=0
type=0
```

Si `selected_file_name` existe se normaliza como ruta absoluta comenzando por
`/` y se usa como selección manual. Si no existe, RDT recibe modo automático.

En la selección RD efectiva `files=all`, el motor conserva
`selected_file_ids=all` pero deja `selected_file_name` vacío. Por tanto, el flujo
normal actual no inventa una ruta llamada “todos los archivos”: envía RDT en
modo automático. Solo una evidencia que traiga un nombre interno real activa
`downloadManualFiles`.

### 23.5 Espera inicial

Tras el upload se busca la nueva fila hasta 30 veces, una vez por segundo. Una
vez localizada, se consulta hasta 45 segundos:

- `healthy_started` o `finished`: respuesta lista;
- error: se borra la fila creada y falla;
- tras 45 segundos, si la fila existe sin error, se devuelve `pending=true`;
- si ni siquiera se encuentra fila, se trata como error.

### 23.6 Seguimiento posterior y limpieza

El worker de seguimiento usa por defecto:

```text
intervalo=15 segundos
timeout=900 segundos
```

Resultados:

- RDT sano/terminado: borrar preflight RD y terminar;
- RDT error: borrar preflight RD y fila RDT con datos;
- timeout: borrar preflight RD y fila RDT con datos;
- excepción: intentar al menos borrar el preflight RD.

La última ejecución real revisada siguió exactamente la rama sana: RDT quedó
preparado, se borró el ID temporal RD y terminó `RDT_FOLLOWUP_DONE`.

## 24. Selección de archivos en RDT

Existen dos mecanismos según la ruta:

### 24.1 API nativa actual

Cuando el contrato trae `selected_file_name`, se envía como
`downloadManualFiles` y `downloadAction=2`. Sin nombre preferido se usa acción
automática.

### 24.2 Compatibilidad qB API de RDT

En rutas de compatibilidad, un worker consulta `/api/v2/torrents/files` hasta 12
veces cada 2 segundos. Selecciona:

1. coincidencia exacta con el archivo preferido;
2. coincidencia similar de al menos 0,86;
3. vídeos no llamados `sample`;
4. cualquier vídeo;
5. si no hay vídeo, el archivo más grande.

Pone prioridad 0 al resto y prioridad 1 a la selección. Esta lógica pertenece a
la capa RDT final y no contradice que la comprobación RD use `files=all`.

## 25. Rama manual no procedente de resultados BTDigg

El endpoint de envío también admite otros módulos. Esa rama no puede validar la
tarjeta contra los resultados BTDigg y aplica una política RD-first más simple.
En ella “RD aceptó” significa que `addMagnet`/`addTorrent` y `selectFiles`
terminaron sin error; no repite la verificación estricta de links usada durante
la búsqueda BTDigg.

### 25.1 Magnet manual

1. hacer precheck RD con `addMagnet` y `selectFiles`;
2. si RD lo acepta, enviarlo a RDT-Client;
3. si RD no lo acepta, enviarlo a qBittorrent;
4. registrar el motor elegido.

### 25.2 URL `.torrent` manual

1. descargar y validar los bytes;
2. hacer precheck RD con `addTorrent`;
3. si RD acepta, subir a RDT-Client;
4. si falla la API RDT compatible, puede escribir el `.torrent` atómicamente en
   el inbox del destino;
5. si RD no acepta, subir los bytes a qBittorrent.

Esta rama no debe copiarse como sustituto de la ruta BTDigg segura: las tarjetas
BTDigg usan el contrato estricto y bloquean resultados sin evidencia, en lugar
de hacer fallback automático solo por haber recibido un clic.

El toggle qB de búsqueda tampoco gobierna esta rama manual: si el precheck RD
manual falla, intenta qB como fallback aunque `qbit_probe_enabled` esté apagado,
porque esa opción controla los probes de búsqueda, no el receptor final manual.

## 26. Registro de una descarga

### 26.1 Cuándo se registra

Se crea un registro nuevo después de que:

- el receptor final acepte una nueva alta; y
- el sistema pueda resolver el hash o conservar evidencia suficiente del envío.

Un clic rechazado, un preflight fallido o una comprobación de duplicado incierta
no crean un falso registro de éxito.

Las ramas `already_present=true` devuelven éxito al usuario, pero no insertan un
nuevo registro en `seguimiento_actual.json`: no hubo una nueva alta que registrar.

### 26.2 Datos conservados

`seguimiento_actual.json` guarda como máximo 50 registros recientes con:

```text
id
title
module
link
hash
destino
rdt_id
route
rd_preflight_id
torrent_path
time
ts
```

El hash se obtiene del resultado, del magnet o del diccionario `info` del
`.torrent`. El ID de registro es independiente del ID RD/RDT y evita depender de
nombres repetidos.

### 26.3 Qué significa el registro

Indica que Buscador RD entregó o reconoció la descarga. No garantiza por sí solo
que el contenido haya terminado de bajar, renombrarse o llegar a una biblioteca.
Los estados posteriores pertenecen al receptor y a otros sistemas.

## 27. Caja negra y trazabilidad

### 27.1 Diagnóstico del job

Cada búsqueda registra una secuencia ordenada con:

- payload y snapshot de configuración;
- comando y directorio ejecutados;
- inicio/fin del proceso;
- páginas y magnets encontrados;
- scoring y criba;
- llamadas y decisiones RD;
- prueba qB o motivo por el que se saltó;
- exportación y cantidad visible;
- estado final y duración.

Los artefactos habituales son:

```text
summary.json
events.jsonl
warnings.jsonl
errors.jsonl
timeline.md
meta.json
```

`summary.json` agrega conteos y últimas decisiones; `events.jsonl` mantiene el
detalle en orden; la timeline ofrece lectura humana.

### 27.2 Seguimiento RD visible

La web consulta `/api/job/{id}/rd-follow` con cursor incremental. El backend
deriva líneas, métricas, magnets enviados y consejos desde la caja negra; no
mantiene una segunda verdad paralela.

### 27.3 Diagnóstico de descarga

Cada clic genera un `trace_id` independiente y eventos como:

```text
DOWNLOAD_CLICK_RECEIVED
BTDIGG_SERVER_CARD_OK
CONTRACT_SUMMARY
DESTINATION_SELECTED
ROUTE_DECIDED
RD_PREFILTER_*
RDT_NATIVE_*
qBittorrent_*
TRACKING_REGISTERED
DOWNLOAD_END_OK / DOWNLOAD_END_PENDING / DOWNLOAD_END_ERROR
```

Las claves que parezcan token, password, authorization o auth no se incorporan
al log textual. Los enlaces se resumen por BTIH o esquema/host/ruta.

### 27.4 Runtime frente a diagnóstico público

El runtime local es la verdad reciente. `diagnostics_public` es una copia
saneada bajo demanda y no se regenera al finalizar cada búsqueda. Una revisión
externa solo verá el último contenido publicado, no necesariamente el fallo más
reciente.

## 28. Cancelación completa

### 28.1 Petición cooperativa

Al pulsar Detener:

1. la web llama `POST /api/job/{id}/cancel`;
2. el job pasa a `cancelling`;
3. se escribe `cancel.json` con la petición;
4. el motor consulta checkpoints antes y durante búsquedas, esperas, RD, qB y
   exportación;
5. las esperas largas están divididas para reaccionar con rapidez.

### 28.2 Limpiezas no cancelables

Una vez detectada la cancelación, determinadas limpiezas ignoran temporalmente
la señal:

- borrar el probe qB creado por el job;
- borrar el temporal RD activo;
- ejecutar el barrido final RD.

La cancelación no debe interrumpir el acto de limpiar lo que la propia búsqueda
creó.

### 28.3 Escalado forzado

Si el subproceso no termina cooperativamente:

```text
30 s desde la petición -> terminate
8 s adicionales        -> kill
```

Cuando se fuerza:

```text
forced_stop=true
cleanup_uncertain=true
```

La web y la caja negra avisan de que puede requerirse revisión. Un proceso
forzado no se presenta como cancelación limpia sin más.

### 28.4 Estados finales de cancelación

- si se pidió cancelar y el proceso termina con código compatible, `cancelled`;
- si se pidió cancelar pero termina de forma incoherente, `error` con mensaje de
  limpieza incierta;
- nunca se promocionan resultados de una cancelación.

## 29. Cola de búsquedas

### 29.1 Construcción

La cola admite hasta 40 elementos. Cada uno guarda:

```text
query
pages
mode
min_gb
qbit_enabled
```

Las consultas vacías se descartan. Los modos desconocidos se convierten a `0`.
El borrador de la web se conserva localmente antes de arrancar.

### 29.2 Exclusión

No puede iniciarse si:

- ya hay una cola activa; o
- existe un job normal/prueba RD activa.

Mientras la cola trabaja, `POST /api/job` también rechaza búsquedas manuales.

### 29.3 Ejecución secuencial

Antes del primer elemento se recuerda el estado global qB. Para cada elemento:

1. escribir su `qbit_enabled` en la configuración viva;
2. crear un job normal con sus parámetros;
3. esperar a que termine;
4. guardar estado, cantidad de resultados y error;
5. continuar con el siguiente aunque el anterior terminara en error;
6. al final, restaurar el qB global anterior.

No se ejecutan elementos en paralelo. Esto mantiene la exclusión del motor y
evita que un elemento cambie qB mientras otro todavía lee la configuración.

### 29.4 Detener y limpiar

Detener la cola:

- pasa el estado a `stopping`;
- cancela el job actual;
- marca los restantes como `cancelled`;
- termina la cola como `cancelled`;
- restaura el qB anterior.

No se puede limpiar una cola activa; primero debe detenerse o terminar.

### 29.5 Reinicio del servicio

El estado se persiste en `search_queue.json`. Si al arrancar el servicio el
fichero dice que la cola estaba `running` o `stopping`, no intenta reanudar a
ciegas: la marca `error`, explica que fue interrumpida y marca como error los
elementos no terminales.

## 30. Comportamiento ante fallos

### 30.1 BTDigg sin resultados

Dos páginas vacías cortan la búsqueda. Cero resultados no es necesariamente
error técnico: el job puede terminar correctamente con lista vacía.

### 30.2 BTDigg bloqueado

`curl_cffi` prueba varias huellas Chrome. Si detecta 429, CAPTCHA, bloqueo,
certificado, acceso prohibido o HTML defectuoso, pasa al rescate Chromium
`--dump-dom`. Si ambos fallan, la excepción termina el job como error y no
promociona artefactos.

### 30.3 Sin token RD

Los candidatos quedan `SIN_TOKEN`. Como el filtro de “solo útiles” se activa
cuando existe token o enlaces directos, una búsqueda sin token puede conservar
filas BTDigg no verificadas para diagnóstico. No deben interpretarse como RD
válidos ni enviarse por la ruta BTDigg segura.

### 30.4 RD temporalmente caído

Los fallos temporales se separan como `RD_ERROR_TEMPORAL`. Si qB está activado,
pueden pasar a la fase qB porque no son positivos RD. Si qB está apagado, no se
presentan como descarga confirmada con la configuración normal de ocultación.

### 30.5 qB desactivado o inaccesible

- desactivado: se salta sin considerar el job fallido;
- login fallido: los candidatos quedan `QBT_OFF`;
- worker fallido: `QBT_ERROR`;
- alta fallida: `QBT_ADD_ERROR`.

La búsqueda puede terminar correctamente aunque qB no aporte ningún positivo.

### 30.6 Fallo de entrega

La fase de búsqueda y la descarga son operaciones distintas. Un job puede haber
terminado bien y un clic posterior fallar porque:

- la tarjeta ya no es vigente;
- cambió la evidencia RD;
- no se pudo comprobar duplicado;
- RDT/qB no responde;
- el `.torrent` ya no está disponible;
- el receptor queda en estado no saludable.

En esos casos se devuelve 4xx/5xx y se registra la causa en la caja negra de
descarga; no se altera retroactivamente el historial de la búsqueda.

## 31. Configuración efectiva relevante

### 31.1 Búsqueda y presentación

```text
default_mode=0
default_pages=1-3
safe_max_pages_when_zero=30
max_results_to_show=80
min_size_gb=0
max_size_gb=400
request_timeout_sec=30
browser_delay_between_pages_sec=2
browser_wait_after_load_sec=5
quality_mode_extra_btdigg_enabled=true
quality_mode_extra_btdigg_pages=1
strict_query_prefilter=true
strict_query_prefilter_keep_discarded_in_exports=true
hide_non_working_results=true
write_exports=true
```

### 31.2 qBittorrent

```text
qbit_probe_enabled=false
qbit_probe_only_non_rd_working=true
qbit_probe_max_candidates=40
qbit_probe_parallel_workers=5
qbit_probe_wait_sec=35
qbit_probe_poll_sec=2
qbit_require_same_file_match=true
qbit_same_file_min_ratio=0.9
qbit_show_metadata_only=false
qbit_delete_probe_after=true
qbit_probe_category=manual
```

### 31.3 Real-Debrid

```text
verify_max_candidates=60
verify_instant_results_with_addmagnet=true
verify_candidates_when_api_off=true
verify_wait_attempts=1 (forzado internamente)
verify_wait_sec=0.25
rd_verify_queue_enabled=true
rd_verify_parallel_workers=60
rd_check_existing_torrents=true
cleanup_failed_verifications=true
cleanup_unselected_verified=true
```

Los límites finos de endpoints, 429, slots, selección y borrado deben copiarse
desde `configuracion-servidor-rd.md`, que es la especificación dedicada.

## 32. Opciones heredadas, inactivas o engañosas

Para replicar el comportamiento real hay que distinguir configuración presente
de configuración efectiva:

### 32.1 `pack_*`

Las opciones `pack_auto_select_best_file`, `pack_hard_skip_without_match`,
`pack_min_video_gb`, `pack_only_video_files` y `pack_query_match_min_ratio`
existen en el JSON, pero no gobiernan actualmente `selectFiles`. RD selecciona
`all` salvo IDs explícitos.

### 32.2 `screen_hide_qbit_not_working`

Está presente y aparece en snapshots, pero el motor efectivo usa
`hide_non_working_results` para construir la lista visible. No debe tratarse
como un segundo filtro activo.

### 32.3 `stop_btdigg_on_429`

Está configurado en `false`, pero la búsqueda web actual usa
`search_btdigg_browser_auto` y sus fallbacks; esa opción no decide el corte en
esa ruta.

### 32.4 Notas `_nota_*`

Las claves de texto son ayuda humana y pueden quedar antiguas. Por ejemplo, una
nota menciona 30 candidatos qB, 24 segundos y ratio 0,85, mientras los valores
efectivos son 40, 35 y 0,9. Para reconstruir se copian valores y código activo,
no comentarios descriptivos obsoletos.

### 32.5 Envío antiguo del editor y JDownloader

`rd_turbo_editor_maestro.py` conserva un modo `--send`, genera enlaces y puede
copiarlos al portapapeles para JDownloader porque
`jdownloader_clipboard_mode=true`. El botón actual de descarga de la web no usa
esa ruta: llama `POST /api/rdt/send` y aplica el contrato seguro RD/RDT/qB
descrito en las secciones 19–24. No se deben mezclar ambas vías al reconstruir
la web vigente.

## 33. Pseudocódigo completo reproducible

```text
function buscar(query, pages, mode, min_gb, qbit_enabled):
    rechazar si existe job o cola activos
    crear runtime aislado y job queued
    lanzar subproceso

    query_normalizada = normalizar(query)
    candidatos = []
    for pagina in parsear_paginas(pages):
        html = curl_cffi_con_fallback_chromium(pagina)
        encontrados = extraer_magnets_y_contexto(html)
        candidatos += encontrados
        cortar tras dos paginas vacias consecutivas

    if mode == CALIDAD and query no contiene marca 4K:
        candidatos += buscar(query + " 2160p", una_pagina)

    candidatos = deduplicar_por_hash_o_enlace(candidatos)
    candidatos = puntuar_segun_modo(candidatos)
    si mode != SIN_FILTRO:
        eliminar score <= -500

    principales, rescate, descartados = cribar_mismo_titulo_o_archivo(candidatos)
    principales = filtrar_tamano_aproximado(principales, min_gb)
    ordenar_para_gastar_RD_en_los_mejores(principales)

    comprobados = comprobar_RD(principales, maximo=60)
    comprobados = volver_a_filtrar_tamano_con_evidencia_RD(comprobados)

    if no hay RD valido and rescate habilitado:
        comprobar_RD(hasta_cinco_mejores(rescate))

    if qbit_enabled:
        no_rd = elegir_no_RD_con_coincidencia_mismo_archivo(comprobados)
        probar_temporalmente_en_qbit(hasta_40, workers=5, espera=35)
        borrar_todos_los_probes_creados

    completos = comprobados + descartados_diagnosticos
    visibles = solo_RD_o_qbit_utiles(comprobados)
    ordenar_RD_primero_qbit_despues(visibles)
    visibles = visibles[:80]

    exportar(completos, visibles)
    guardar shown aislado
    limpiar_temporales_RD_de_busqueda
    si subproceso termina bien:
        promover artefactos compartidos
        guardar historial
    devolver visibles

function descargar(tarjeta_cliente):
    tarjeta = recargar_tarjeta_desde_servidor_o_historial()
    exigir indice_hash_y_enlace_coherentes(tarjeta_cliente, tarjeta)
    contrato = reconstruir_desde_raw_servidor(tarjeta)
    destino = clasificar_movies_o_tv(contrato.title)

    if RD reutilizable ya existente:
        refrescar evidencia RD
        evitar duplicado RDT
        reutilizar o importar en RDT
    else if qB vivo:
        evitar duplicado qB
        reutilizar o añadir en qB
    else if RD verificado con links:
        evitar duplicado RDT
        crear preflight RD nuevo
        importar en RDT
        seguir RDT y borrar preflight
    else:
        bloquear por falta de evidencia segura

    registrar solo si receptor acepto o ya lo tenia
```

## 34. Invariantes que no deben romperse al replicar

1. Una búsqueda y una cola nunca ejecutan el motor a la vez.
2. Cada job escribe primero en su runtime aislado.
3. Solo un job exitoso reemplaza los resultados compartidos.
4. BTDigg encontrado no equivale a torrent válido.
5. Las palabras de la consulta deben coincidir en el mismo título/archivo.
6. Modo sin filtro no desactiva validaciones técnicas.
7. `instantAvailability` no equivale a `RD_OK`.
8. qB solo llama vivo a evidencia real; metadatos solos no bastan actualmente.
9. Los probes qB creados por la búsqueda se borran; los preexistentes no.
10. Los temporales RD de búsqueda se borran antes de terminar.
11. El clic se valida contra el servidor; el navegador no decide la ruta.
12. Un “no pude comprobar duplicado” bloquea el alta, no permite duplicar.
13. Un RD existente se refresca y nunca se borra como temporal.
14. Un RD verificado no existente recibe preflight nuevo al descargar.
15. El preflight RD vive hasta que RDT está encaminado y luego se limpia.
16. Fallos temporales no se etiquetan como torrents muertos.
17. Resultados rechazados pueden conservarse en export, no en la tabla limpia.
18. Cancelar incluye limpiar; forzar cancelación deja advertencia explícita.
19. El historial normal y el historial sin semillas son verdades distintas.
20. Ningún token, password o autorización entra en documentación o diagnóstico
    público.

## 35. Mapa mínimo de implementación

| Área | Archivo/símbolo principal |
|---|---|
| Entrada web y endpoints | `app/api/btdigg_rd/routes.py` |
| Supervisión del job | `app/api/btdigg_rd/jobs.py` |
| Runtime aislado | `app/api/btdigg_rd/_runtime_dirs.py` |
| Promoción de artefactos | `app/api/btdigg_rd/_job_artifacts.py` |
| Cola | `app/api/btdigg_rd/search_queue.py` |
| Puente web-motor | `app/motor/btdigg/rd_turbo_editor_maestro.py` |
| Búsqueda, scoring, filtros, RD/qB | `app/motor/btdigg/rd_turbo_pro.py` |
| Probe qB | `app/motor/btdigg/_motor_qbt_probe.py` |
| Reintentos RD | `app/motor/btdigg/_motor_rd_retry.py` |
| Exportación | `app/motor/btdigg/_motor_exports.py` |
| Saneado de resultados | `app/api/btdigg_rd/results.py` |
| Historial | `app/api/btdigg_rd/history.py` |
| Contrato y decisión de descarga | `app/api/btdigg_rd/_send_contracts.py` |
| Entrega final | `app/api/btdigg_rd/send.py` |
| Cliente qB | `app/api/btdigg_rd/_qbt_client.py` |
| Cliente RD | `app/api/btdigg_rd/_rd_client.py` |
| Contrato nativo RDT | `app/api/btdigg_rd/_rdt_client.py` |
| Clasificación movies/tv | `app/api/btdigg_rd/classification.py` |
| Caja negra | `app/api/btdigg_rd/blackbox.py` |
| Interfaz y reconexión | `app/web/static/js/btdigg-rd.js` |

## 36. Criterio de equivalencia para otro proyecto

Otro proyecto se comporta como este buscador únicamente si reproduce las
decisiones, no solo los nombres de botones:

- obtiene y deduplica los mismos candidatos;
- aplica los tres modos con las mismas reglas;
- evita coincidencias repartidas en packs;
- limita y ordena antes de gastar RD/qB;
- separa positivo, negativo, desconocido y temporal;
- prueba qB de forma temporal y limpia;
- mantiene resultados de último éxito;
- revalida la tarjeta y el duplicado en el momento de descarga;
- conserva preflight RD hasta entrega RDT;
- deja trazabilidad suficiente para explicar cada descarte y cada ruta.

Copiar solo la consulta a BTDigg, el token RD o un fallback qB no reproduce el
sistema. El comportamiento completo es la suma ordenada de todos los contratos
descritos en este documento y en `configuracion-servidor-rd.md`.

## 37. Evidencia real usada para contrastar esta especificación

La última búsqueda completa revisada en la caja negra no se usa como regla, pero
demuestra el orden real de las fases:

```text
consulta=Holmes 3
páginas=1-5
modo=1
mínimo=0
BTDigg únicos=10
criba principal=10
qB habilitado=false
RD_OK=2
RD_FAIL=7
NO_INSTANT=1
resultados mostrados=2
errores de diagnóstico=0
duración=36,84 s
```

La secuencia observada fue:

```text
JOB_STARTED
CONFIG_SNAPSHOT
PROCESS_STARTED
búsqueda BTDigg base
rescate de calidad 2160p
scoring
criba de consulta
endpoint instantAvailability desactivado (37)
fallback serio addMagnet
cola RD y slots activos
selectFiles=all
2 verificaciones RD correctas
rechazos terminales y descarte sin progreso
qB omitido por OFF
exportación
limpieza de temporales
JOB_FINISHED_OK
```

La descarga real más reciente revisada confirmó la otra mitad del contrato:
preflight RD, alta RDT, detección de RDT preparado, borrado correcto del
preflight y `RDT_FOLLOWUP_DONE`.

La web real respondió HTTP 200 en escritorio y móvil, mostró qB OFF, dos
resultados RD y cero errores de consola, página o red. La persistencia volvió a
la misma vista tras recargar. En móvil, la tabla de 860 px se desplazó dentro de
su contenedor sin aumentar el ancho del `body`.

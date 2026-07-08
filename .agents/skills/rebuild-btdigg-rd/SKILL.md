---
name: rebuild-btdigg-rd
description: Reconstruir y validar el servicio Docker principal btdigg-rd dentro del proyecto unificado Z:\buscador-rd. Usar despues de cambios en web, backend, frontend, Docker, requisitos, configuracion funcional o cualquier cambio que deba quedar levantado en el puerto 9007.
---

# Rebuild BTDigg + RD

## Flujo

1. Confirmar que el cambio afecta al servicio principal `btdigg-rd`.
2. Ejecutar `git status --short` para saber si hay cambios pendientes antes del rebuild.
3. Ejecutar el script desde `Z:\buscador-rd`.
4. Revisar salida de rebuild, contenedor y HTTP.
5. Si falla, responder con causa probable, archivo tocado y error clave.

## Comando

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\rebuild-btdigg-rd\scripts\rebuild_and_check.ps1
```

## Reglas

- No pedir confirmacion para rebuild del servicio principal cuando el cambio lo requiera.
- No tocar replicas ni otros servicios.
- Usar bloque remoto limpio por SSH; no meter comandos largos con comillas anidadas.
- No usar `ssh "... python3 -c ..."` para comprobaciones delicadas.
- Para Python remoto, usar `scripts/remote_python_check.ps1`, que manda el codigo por stdin y valida primero `REMOTE_STDIN_OK`.
- Validar siempre contenedor y HTTP `9007`.
- No declarar caida por un primer HTTP temporal tras rebuild; el script debe reintentar antes de fallar.
- Si la carpeta esta sucia, distinguir cambios previos de cambios hechos en esta pasada.

## Python remoto limpio

Probe minimo:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\rebuild-btdigg-rd\scripts\remote_python_check.ps1 -ProbeOnly
```

Con archivo local:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\rebuild-btdigg-rd\scripts\remote_python_check.ps1 -ScriptPath .\tmp\check.py
```

Con codigo en variable:

```powershell
$code = @'
print("hola desde NAS")
'@
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\rebuild-btdigg-rd\scripts\remote_python_check.ps1 -Code $code
```

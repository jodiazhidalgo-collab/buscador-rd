---
name: replicate-btdigg-rd
description: Replicar desde la raiz unificada Z:\buscador-rd hacia replicas externas antiguas solo cuando el usuario lo pida expresamente. No usar para trabajo normal del proyecto.
---

# Replicar desde Buscador RD

## Flujo

1. Confirmar permiso explicito del usuario.
2. Revisar que el cambio principal funciona desde `Z:\buscador-rd` y puerto `9007`.
3. Crear backup de las replicas antes de tocar nada.
4. Copiar solo los archivos necesarios.
5. Adaptar unicamente nombre, ruta, servicio y puerto.

## Mapeo

- Principal: `Z:\buscador-rd` / `btdigg-rd` / `9007`
- Replica 2 externa: `Z:\web\BTDigg + RD 2` / `btdigg-rd-2` / `9027`
- Replica 3 externa: `Z:\web\BTDigg + RD 3` / `btdigg-rd-3` / `9037`

## Reglas

- No replicar por iniciativa propia.
- No usar esta skill para trabajo normal en `Z:\buscador-rd`.
- No tocar otros proyectos del compose maestro.
- No copiar runtime, backups, tokens, diagnosticos ni historial.
- Si el cambio no esta validado en principal, parar.

---
name: cerrar-git-btdigg-rd
description: Cerrar Git del proyecto unificado Z:\buscador-rd al finalizar el turno de trabajo. Ejecuta limpieza de residuos, commit local si hay cambios y push al remoto configurado.
---

# Cerrar Git BTDigg + RD

## Cuando usarla

Uso obligatorio al finalizar el turno de trabajo cuando se hayan modificado archivos en `Z:\buscador-rd`.

Tambien usar si el usuario pregunta si Git esta sucio y pide dejarlo limpio.

No usar en turnos de solo lectura. Si Git esta limpio al empezar, el script sale
sin limpiar, crear carpetas, hacer commit ni hacer push.

No dejes cambios locales sin commit y push salvo peticion expresa del usuario. Si el trabajo queda incompleto pero el usuario pidio avanzar y cerrar, usa un mensaje `wip: ...`.

## Flujo

1. Confirmar que estas en `Z:\buscador-rd`.
2. Ejecutar `git status --short` antes de cualquier limpieza.
3. Si no hay cambios, salir sin hacer nada.
4. Si hay cambios, ejecutar `limpiar-residuos-btdigg-rd` y hacer commit.
5. Limpiar de nuevo los residuos creados por el hook del commit.
6. Hacer push al remoto configurado y confirmar que Git queda limpio.

## Comando

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\cerrar-git-btdigg-rd\scripts\close_git.ps1 -Message "mensaje corto"
```

Si solo se modificaron archivos locales ignorados por Git, permite la limpieza
explicita sin commit ni push:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\cerrar-git-btdigg-rd\scripts\close_git.ps1 -ForceCleanup
```

## Reglas

- No configurar remotos nuevos.
- No usar `-ForceCleanup` en una revision de solo lectura.
- No borrar codigo ni tests para limpiar.
- No usar `git reset`, `git checkout` ni comandos destructivos.
- No uses `-NoCommit` ni `-NoPush` salvo peticion expresa del usuario.
- Si el trabajo esta a medias pero el usuario pidio cerrar Git, hacer commit local con mensaje `wip: ...`.
- Si hay secretos o runtime ignorado por `.gitignore`, no forzarlo al commit.
- La respuesta final debe decir el commit creado y el push realizado.

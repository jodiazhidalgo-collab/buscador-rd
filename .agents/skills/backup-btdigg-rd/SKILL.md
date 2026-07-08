---
name: backup-btdigg-rd
description: Crear backups fechados del proyecto unificado Z:\buscador-rd antes de cambios delicados. Usar antes de editar AGENTS, .codex, skills, frontend, backend, motor RD/qB, Docker, Cloudflared, Whisper, configuracion funcional o cualquier zona donde el usuario espere salvavidas local.
---

# Backup Buscador RD

## Flujo

1. Identificar que archivos o carpetas se van a tocar.
2. Ejecutar `git status --short` desde `Z:\buscador-rd` y avisar si la carpeta ya esta sucia.
3. Crear un motivo corto, en minusculas y con guiones.
4. Ejecutar `scripts/create_backup.ps1` desde la raiz del proyecto.
5. Verificar que el ZIP aparece en `Z:\buscador-rd\_backups`.
6. Informar el nombre del backup antes de editar.

## Comando

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\backup-btdigg-rd\scripts\create_backup.ps1 -Reason "motivo-corto"
```

Para comprobar sin crear ZIP:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\backup-btdigg-rd\scripts\create_backup.ps1 -Reason "motivo-corto" -DryRun
```

## Reglas

- El unico directorio de backups valido es `Z:\buscador-rd\_backups`.
- No crear backups dentro de `services\btdigg-rd`, `config\cloudflared`, `config\whisper` ni subcarpetas sueltas.
- No meter `_backups/` en Git.
- Si el cambio toca secretos o configuracion runtime, el backup puede ser local, pero nunca debe ir a commit.
- El backup por defecto incluye instrucciones, skills, `.codex`, compose y `services`, excluyendo runtime pesado.
- Si hay cambios previos, no los presentes como propios; separa cambios previos y cambios nuevos.

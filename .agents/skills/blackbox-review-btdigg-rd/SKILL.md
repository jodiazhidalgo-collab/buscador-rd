---
name: blackbox-review-btdigg-rd
description: Revisar diagnosticos blackbox de BTDigg + RD antes de tocar RD, qBittorrent, jobs, seguimiento, descargas o fallos visibles del flujo. Usar para resumir ultimo summary/events/errors/warnings y separar fallo real de ruido.
---

# Blackbox Review BTDigg + RD

## Flujo

1. No editar codigo al empezar.
2. Si la revision es para ChatGPT/GitHub, leer primero `diagnostics_public`.
3. Si estas en local y hace falta crudo, leer `config\btdigg-rd\data\diagnostics\btdigg`.
4. Localizar el diagnostico mas reciente util.
5. Resumir estado, ultimo evento, errores y warnings.
6. Indicar si el problema es UI, motor, diagnostico, RD, qB o red.

## Comando

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\blackbox-review-btdigg-rd\scripts\check_latest_blackbox.ps1
```

## Reglas

- No volcar logs enormes.
- No mostrar tokens ni credenciales.
- Para publicar evidencia, usar `diagnostics_public`; no subir runtime crudo.
- Si hay contradiccion entre UI y logs, la UI manda para comportamiento visible.
- Si no hay diagnosticos recientes, decirlo claro y no inventar.

---
name: playwright-ui-check-btdigg-rd
description: Validar visualmente la web btdigg-rd del proyecto Z:\buscador-rd en navegador. Usar despues de cambios de interfaz o cuando el usuario reporte comportamiento visible, botones, pestanas, tarjetas, estado, consola, red o persistencia localStorage.
---

# Playwright UI Check BTDigg + RD

## Flujo

1. Abrir `http://192.168.1.159:9007/`.
2. Comprobar que carga la herramienta real, no una pagina en blanco.
3. Revisar consola y red si hay fallo visible.
4. Probar solo el flujo afectado por el cambio.
5. Si se tocan pestanas, filtros o secciones, comprobar persistencia tras recargar.

## Comando

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\playwright-ui-check-btdigg-rd\scripts\ui_check.ps1
```

Opcional:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\playwright-ui-check-btdigg-rd\scripts\ui_check.ps1 -Url http://192.168.1.159:9007/
```

## Reglas

- La validacion visible manda sobre logs internos cuando el fallo es de UI.
- No uses esta skill para cambiar codigo; solo para comprobar y recoger evidencia.
- No hagas pruebas destructivas ni lances descargas reales sin permiso.
- En respuesta final, indica URL, resultado visible, consola/red y captura si procede.

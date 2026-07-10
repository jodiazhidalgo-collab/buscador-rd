---
name: playwright-ui-check-btdigg-rd
description: Validar visualmente la web btdigg-rd del proyecto Z:\buscador-rd en navegador. Usar despues de cambios de interfaz o cuando el usuario reporte comportamiento visible, botones, pestanas, tarjetas, estado, consola, red o persistencia localStorage.
---

# Playwright UI Check BTDigg + RD

## Flujo

1. Abrir `http://192.168.1.159:9007/`.
2. Usar por defecto Chrome/Edge del sistema, detectado sin depender solo de PATH.
3. Comprobar que carga la herramienta real, no una pagina en blanco.
4. Validar desktop y mobile con capturas.
5. Revisar consola JS, errores de pagina, red y respuestas HTTP con error.
6. Comprobar overflow horizontal y persistencia de una vista tras recargar.
7. Probar solo el flujo afectado por el cambio.
8. Si un elemento lleva `data-allow-horizontal-scroll`, tratarlo como scroll interno permitido y reportarlo separado del overflow real de pagina.

## Comando

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\playwright-ui-check-btdigg-rd\scripts\ui_check.ps1
```

Opcional:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\playwright-ui-check-btdigg-rd\scripts\ui_check.ps1 -Url http://192.168.1.159:9007/
```

Fallback explicito si Chrome/Edge del sistema no sirve:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\playwright-ui-check-btdigg-rd\scripts\ui_check.ps1 -AllowBundledChromium
```

## Reglas

- No ejecutar esta skill en revisiones generales de solo lectura ni para cambios
  no visuales. Usarla tras un cambio de UI o si el usuario pide la comprobacion.
- La validacion visible manda sobre logs internos cuando el fallo es de UI.
- No uses esta skill para cambiar codigo; solo para comprobar y recoger evidencia.
- No hagas pruebas destructivas ni lances descargas reales sin permiso.
- No descargues Chromium automaticamente en el flujo normal.
- El fallback a Chromium de Playwright debe ser explicito, no automatico.
- En respuesta final, indica URL, navegador usado, resultado visible, consola/red, overflow, persistencia y captura si procede.
- No marques como fallo los textos largos dentro de una zona marcada con `data-allow-horizontal-scroll`; eso es comportamiento visible esperado.

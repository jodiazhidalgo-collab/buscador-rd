---
name: investigacion-avanzada-buscador-rd
description: Preparar un prompt listo para copiar y pegar en ChatGPT, investigacion avanzada, deep research u otra IA cuando el usuario quiera analizar un problema de Buscador RD. Usar cuando el usuario diga investigacion avanzada, pasame lo que tengo que pegar, prompt para ChatGPT, que lo mire ChatGPT, analisis avanzado, investigar problema fuera de Codex, o formule una peticion parecida sobre el repo jodiazhidalgo-collab/buscador-rd.
---

# Investigacion avanzada Buscador RD

## Objetivo

Generar un texto listo para copiar/pegar en ChatGPT u otra IA externa. No resuelvas el problema aqui si el usuario esta pidiendo el prompt; prepara la investigacion para que la otra IA mire GitHub con el contexto correcto.

## Reglas

1. Incluir siempre el repo `jodiazhidalgo-collab/buscador-rd` y la rama `master`.
2. Indicar que mire primero `README.md`, `AGENTS.md`, `docs/AI_REVIEW.md`, `.agents/skills/`, `.github/workflows/ci.yml`, `services/btdigg-rd/tests/` y `diagnostics_public/`.
3. Explicar el motivo concreto que da el usuario sin inventar datos.
4. Pedir analisis por evidencias, con rutas y archivos concretos.
5. Pedir que no devuelva el repo entero ni logs completos; solo hallazgos, hipotesis, pruebas y cambios recomendados.
6. Recordar que secretos, tokens, passwords y API keys no deben pedirse ni imprimirse.
7. Si el problema depende de datos vivos recientes, indicar que primero debe haberse hecho `Push` desde la web o desde Git para que GitHub tenga el ultimo `diagnostics_public/`.

## Plantilla

Usa esta forma y adapta solo el bloque de problema:

```text
Quiero una investigacion avanzada sobre el proyecto GitHub:

Repositorio: jodiazhidalgo-collab/buscador-rd
Rama: master

Problema a investigar:
[PEGAR AQUI EL PROBLEMA CONCRETO DEL USUARIO]

Instrucciones:
- Revisa el repo en GitHub, no trabajes de memoria.
- Empieza por README.md, AGENTS.md y docs/AI_REVIEW.md para entender el flujo real.
- Revisa .agents/skills/ para conocer las rutinas operativas del proyecto.
- Revisa diagnostics_public/ para ver diagnosticos, jobs, logs saneados, JSON, historial y errores publicados.
- Revisa .github/workflows/ci.yml y services/btdigg-rd/tests/ para entender las pruebas existentes.
- Si el diagnostico depende de una busqueda o fallo reciente, asume que solo esta disponible si se hizo Push despues del fallo.
- No pidas ni muestres tokens, passwords, API keys, cookies ni secretos.
- No pegues el repo entero ni logs completos.
- Devuelveme un informe ordenado con:
  1. archivos revisados;
  2. hechos comprobados;
  3. hipotesis mas probables;
  4. pruebas concretas que recomiendas;
  5. cambios propuestos, con rutas exactas;
  6. riesgos o dudas reales.
- Incluye una entrega final para Codex con instrucciones ejecutables por fases:
  1. estructura o archivos a tocar, si aplica;
  2. ajustes concretos;
  3. pruebas y validaciones;
  4. orden recomendado de ejecucion.
- Para cada fase indica rutas exactas, cambios esperados y comandos de prueba.
- No propongas cambios genericos: la entrega debe ser accionable para Codex.
```

## Salida

Responder con el prompt final en un bloque de texto facil de copiar. Antes del bloque, anadir solo una frase corta si hace falta aclarar que debe hacerse Push para publicar datos recientes.

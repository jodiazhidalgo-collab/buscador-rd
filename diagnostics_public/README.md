# Diagnostico publico Buscador RD

Esta carpeta es el espejo publico saneado para ChatGPT, Codex y revisiones externas.

Incluye runtime, jobs, logs, JSON, seguimiento, historial y exportaciones legibles.
Los tokens, passwords, API keys, Authorization, cookies y secretos parecidos se sustituyen por `***REDACTED***`.
Los magnets, hashes, rutas, nombres, busquedas, URLs, estados RD/qB y errores se mantienen visibles.

Entradas principales:

- `btdigg/`: copia saneada de `config/btdigg-rd/data`.
- `manifest.json`: lista completa de ficheros exportados, omitidos y redacciones.
- `*_export/`: bases SQLite volcadas a JSON legible.

Para que GitHub/ChatGPT vea cambios nuevos, hay que regenerar esta carpeta y hacer commit/push.

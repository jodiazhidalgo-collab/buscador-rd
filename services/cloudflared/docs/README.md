# Cloudflared

Pieza separada para exponer una web interna por HTTPS sin mezclarla con el proyecto de la app.

## Estructura

- `config/`: variables publicas y secretos locales.
- `worker/`: Worker que hace de proxy HTTPS fijo.
- `watcher/`: vigilante interno que publica la URL viva del tunel.
- `data/estado/`: estado generado para uso humano.
- `logs/`: registros separados.

## Flujo

1. El contenedor `cloudflared` abre un Quick Tunnel hacia la web interna configurada.
2. El vigilante interno lee la URL `trycloudflare.com`.
3. El vigilante actualiza Cloudflare KV con la URL viva.
4. El Worker `cloudflared` sirve una URL HTTPS fija y proxifica a la URL viva.

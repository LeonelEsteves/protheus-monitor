# Project Memory (GAMB / Protheus Monitor)

## HTTPS / TLS

- `GAMB_FORCE_HTTPS=1`: redirects `http://` to `https://` (302). Use only when HTTPS is actually available (reverse proxy or TLS enabled).
- `GAMB_BEHIND_PROXY=1`: enables `ProxyFix` so `X-Forwarded-Proto`/`X-Forwarded-Host` are respected (typical when running behind IIS/Nginx/Apache).
- `GAMB_SSL_CERT_FILE` + `GAMB_SSL_KEY_FILE`: enables TLS directly on Flask `app.run(..., ssl_context=(cert, key))`.

Notes:
- Browser “Not secure” disappears only with a certificate trusted by the client (corporate CA / Let’s Encrypt / proper PKI). A self-signed certificate will still show a warning.

## Frontend Offline

- Tailwind is vendored locally at `static/vendor/tailwindcss.js`.
- Main templates use the local script instead of `https://cdn.tailwindcss.com`, so the layout still renders without internet access.

## Auditoria

- events_log.json deve registrar apenas entrada e saida do sistema: LOGIN e LOGOUT bem-sucedidos.
- Nao registrar trilha HTTP, negacoes de acesso, tentativas de login invalidas ou invalidacao automatica de sessao no log de acesso.


- Saude do coletor: COLLECTOR_HEALTH deve gerar log apenas quando a sincronizacao nao estiver sendo feita (coletor parado/desatualizado), sem registrar estado sincronizado/normal.


- Alertas configuraveis: usar `alert_settings.json` para habilitar/desabilitar monitoramento de disco critico (<=10%), servicos de prioridade alta parados, Windows Update pendente e ausencia do `status-servico.json` do coletor no host.
- Tela inicial deve ter botao de alertas ao lado do sino de logs, com badge e modal no mesmo padrao visual.


- Estrutura organizada: arquivos operacionais do monitor foram centralizados em data/ (users, environments, servers, alert_settings, events_log).

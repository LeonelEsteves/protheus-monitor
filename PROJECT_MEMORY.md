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

- Regra duravel: novas atualizacoes tecnicas relevantes do ambiente/sistema devem ser registradas no README.md da raiz; a tela principal exp�e esse conteudo para todos os usuarios autenticados.

## Regras recentes de monitoramento e alertas

- Windows Updates: em todo o sistema considerar apenas atualizacoes de software (`Type='Software'`), ignorando drivers e outros tipos opcionais.
- Total de updates por ambiente: somar separadamente por `server_ip` de cada JSON do coletor e incluir somente hosts online, com `status-servico.json` presente e coletor sincronizado; hosts offline, sem JSON ou stale devem aparecer como `N/D` e nao entrar na soma.
- Webhook/Teams: URL do webhook deve ficar somente em `data/secret_settings.json` ou variavel de ambiente, nunca em arquivo versionado.
- Webhook/Teams: alertas devem ser enviados separadamente, um Adaptive Card por alerta, com icone por cenario, campos organizados e cor conforme criticidade.
- Webhook/Teams: envio deve respeitar configuracao de ativo/inativo, dias da semana, horario/full-time e severidades (`critical`, `warning`, `info`).
- Webhook/Teams: manter deduplicacao para evitar repeticao excessiva; alertas repetidos so devem reenviar apos a janela configurada.
- Coletor: sempre que houver alteracao nos arquivos do coletor, gerar uma nova versao curta em `gamb-coletor/versions` (padrao `vYYYYMMDD` ou `vYYYYMMDD-HHMMSS`).
- Interface: manter tema dark como padrao unico; inputs, campos de confirmacao e areas de digitacao em modais nunca devem usar fundo branco.
- Windows Update no webhook: enviar no maximo uma vez por dia por ambiente/servidor, mesmo que a quantidade de updates mude durante o dia.

- Tela principal de servicos: exibir o valor bruto de windows_updates_pending vindo do JSON por host quando existir; a validacao de sincronismo deve afetar soma/webhook, nao esconder o numero da tela.

- Cards de Windows Update no Teams devem ler o JSON fresco de cada host no momento do envio, usar server_ip e windows_updates_pending do proprio JSON, deduplicar por server_ip e nunca usar soma agregada/cache antigo para a contagem.

- Painel admin deve ter botao para envio imediato de todos os alertas elegiveis ao webhook/Teams; esse envio manual nao altera agenda/tempo configurado e usa a configuracao atual de severidades/webhook.

- Ordenacao de servicos: na tela principal e no cadastro de ambientes, homologacao/desenvolvimento devem exibir servicos por display_name; producao deve preservar a ordem cadastrada/original.

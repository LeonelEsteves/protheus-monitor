Arquivos operacionais do monitor.

Conteudo esperado:
- `users.json`: usuarios e perfis
- `environments.json`: ambientes e servicos monitorados
- `servers.json`: inventario de servidores
- `alert_settings.json`: configuracao da rotina de alertas
- `events_log.json`: trilha operacional e auditoria resumida
- `execution_trace.json`: trilha tecnica detalhada de start/stop/restart por ambiente, host e servico

- `alert_delivery_state.json`: controle de envio/deduplica??o de alertas externos, como Teams.
- `secret_settings.json`: segredos locais, como webhook do Teams. Este arquivo deve ficar fora do Git.

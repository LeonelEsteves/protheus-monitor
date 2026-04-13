# Memória do Projeto (Protheus Monitor)

Use este arquivo para registrar decisões e instruções duráveis sem precisar reler o código inteiro.

## Decisões / instruções (adicione em ordem cronológica)

- 2026-04-13: Criado `AGENTS.md` para funcionar como “CLAUDE.md” do Codex e manter contexto persistente.
- 2026-04-13: Schema de serviços atualizado (`tcp_port`, `webapp_port`, `service_ip`, `console_log_file`, `priority`) + novo perfil `technical` + operador bloqueado de `producao`.
- 2026-04-13: Adicionada “Busca automática” no admin (`POST /discover-services`) via PowerShell Remoting para descobrir serviços TOTVS e ler `appserver.ini`.

## Comandos úteis (preencher quando confirmado)

- Executar o app (exemplo): `py -m flask --app app.py run --host 0.0.0.0 --port 5000`
- Dependências (exemplo): `pip install flask werkzeug pywin32`

## Checklist de contexto (manter curto)

- O app controla serviços do Windows com `win32serviceutil` (start/stop/restart).
- Dados ficam em `users.json`, `environments.json`, `events_log.json`.

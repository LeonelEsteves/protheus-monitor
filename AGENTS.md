# Protheus Monitor (Codex)

Este repositório é um app **Flask** (Windows) para **monitorar e controlar serviços do Windows** relacionados ao Protheus/TOTVS por ambiente, com autenticação e painel web.

## Como o Codex deve “lembrar” deste projeto

- **Use este `AGENTS.md` como memória persistente do projeto** (equivalente ao `CLAUDE.md`).
- Quando o usuário der **novas instruções duráveis** (padrões, decisões, comandos, arquitetura, convenções), **atualize este arquivo** antes de encerrar a tarefa, mantendo-o curto e objetivo.
- Para detalhes mais longos (log de decisões/comandos confirmados), mantenha também `PROJECT_MEMORY.md` atualizado.
- Evite reler o repo inteiro: comece por aqui e só abra arquivos quando precisar de detalhes.

## Estrutura (principais arquivos)

- `app.py`: servidor Flask + regras de auth + rotas + integração com `win32serviceutil`.
- `templates/index.html`: painel principal (status/ações por ambiente).
- `templates/admin.html`: painel admin (usuários/ambientes).
- `templates/login.html`: tela de login.
- `users.json`: base de usuários (hash de senha + role + active).
- `environments.json`: cadastro de ambientes e serviços (appserver/rest/etc).
- `environments.json` (serviços): `path_executable`, `tcp_port`, `webapp_port`, `rest_port`, `service_ip`, `console_log_file`, `priority` (`baixa`/`media`/`alta`).
- `events_log.json`: log de ações (start/stop/restart) e alertas.
- Auto-discovery (admin): endpoint `POST /discover-services` tenta descobrir serviços via PowerShell Remoting (WinRM) e ler `bin\\appserver.ini`.

## Regras de negócio (resumo)

- Autenticação por sessão (`session["username"]`); usuário pode ser desativado (`active: false`).
- Papéis: `admin` (acesso ao `/admin` e APIs de users/environments), `technical` (operação + acesso a produção) e `operator` (operação sem produção).
- Ações disponíveis por serviço: `start`, `stop`, `restart` (via `win32serviceutil.*`).
- Status dos ambientes é calculado por ambiente e pode ser buscado em paralelo (`ThreadPoolExecutor`).
- Regra: `operator` não pode acessar ambientes `environment_type=producao` (index/status/action filtram/bloqueiam).
- `service_ip` (quando informado) é usado para status/ações do serviço (sobrescreve o host do ambiente).

## Configuração / variáveis de ambiente (importante)

- `APP_SECRET_KEY`: segredo da sessão (trocar em produção).
- `PROTHEUS_ADMIN_USER` / `PROTHEUS_ADMIN_PASSWORD`: credenciais iniciais do admin (cria `users.json` se não existir).

## Integrações externas (opcional)

- Teams webhook e SMTP existem, mas podem estar desabilitados por configuração vazia.

## Convenções para mudanças

- Preferir mudanças **mínimas** e consistentes com o estilo atual.
- Não quebrar o formato de `users.json` e `environments.json` (backward compatibility).
- Ao alterar HTML/JS, manter a UI funcional sem depender de bundlers (projeto simples).

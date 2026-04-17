# Protheus Monitor

Aplicação Flask para monitoramento operacional de ambientes Protheus/TOTVS em Windows, com autenticação, painel web, descoberta automática de serviços, leitura de metadados via coletor e ações remotas de operação.

## Visão Geral

O sistema foi desenhado para centralizar a operação de ambientes Protheus por ambiente, não apenas por servidor. Cada ambiente reúne:

- serviços de aplicação
- serviços de infraestrutura
- metadados de acesso
- estado do coletor
- alertas operacionais
- trilha resumida de auditoria

O backend é um único `app.py`, com templates server-side em Jinja/HTML e JavaScript simples, sem bundler.

## Arquitetura

### Backend

- `app.py`: aplicação Flask, autenticação, regras de negócio, fila de jobs, integração com serviços Windows, leitura do coletor, alertas, administração e versionamento do coletor.

### Frontend

- `templates/index.html`: painel principal de operação.
- `templates/admin.html`: painel administrativo.
- `templates/login.html`: autenticação.
- `templates/server_inventory.html`: inventário/consulta de servidores.
- `static/`: assets locais, incluindo Tailwind local.

### Dados locais

Os arquivos operacionais ficam centralizados em `data/`:

- `data/users.json`: usuários, senha hash, perfil e status.
- `data/environments.json`: cadastro dos ambientes e serviços monitorados.
- `data/servers.json`: inventário de servidores.
- `data/alert_settings.json`: configuração da rotina de alertas.
- `data/events_log.json`: log operacional e auditoria resumida.
- `data/execution_trace.json`: trilha técnica de execução de ações por host/serviço, usada para diagnóstico.

### Coletor

O monitor usa o `gamb-coletor` como fonte primária de verdade para status e metadados:

- `gamb-coletor/versions/`: versões empacotadas do coletor
- `gamb-coletor/versions/new-collector-version.ps1`: rotina para gerar nova versão snapshot do coletor

No servidor monitorado, o arquivo consumido é:

- `C:\gamb-coletor\status-servico.json`

## Como o Sistema Funciona

### 1. Cadastro de ambiente

Cada ambiente possui:

- `name`
- `environment_type`
- `host`
- `app_url`
- `rest_url`
- `erp_version`
- `database_update_date`
- `services`
- `infra_services`

Cada serviço pode ter:

- `name`
- `display_name`
- `path_executable`
- `tcp_port`
- `webapp_port`
- `rest_port`
- `service_ip`
- `console_log_file`
- `priority`

### 2. Coleta de status

O monitor lê o `status-servico.json` por host via caminho local/UNC e hidrata o ambiente com:

- status dos serviços
- IP e nome do servidor
- timestamp da última sincronização
- discos
- atualizações pendentes do Windows
- metadados do `appserver.ini`

Durante a sincronização com o coletor, o monitor também verifica se os hosts do ambiente estão acessíveis. Quando um host não responde, o sistema passa a sinalizar que o servidor está possivelmente desligado ou inacessível.

Em ambientes com múltiplos hosts, o monitor só considera a sincronização do coletor saudável quando todos os hosts relevantes do ambiente estiverem online e com JSON/timestamp válidos.

O sistema evita consultar o status diretamente no Windows como fonte principal. O coletor é a referência operacional.

### 3. Operação de serviços

As ações disponíveis são:

- `start`
- `stop`
- `restart`
- ações em lote por ambiente

As execuções usam fila assíncrona para reduzir latência na UI. A confirmação de resultado usa o status refletido pelo coletor.

### 4. Descoberta automática

O endpoint de descoberta lê exclusivamente o JSON do coletor para montar serviços do ambiente. O objetivo é reduzir dependência de WinRM e padronizar a origem dos metadados.

### 5. Alertas

A rotina de alertas avalia:

- ausência do `status-servico.json`
- pouco espaço em disco
- updates pendentes do Windows
- serviços de prioridade alta parados fora de produção
- qualquer serviço parado em ambientes de produção

Os alertas são deduplicados para evitar repetição visual e ruído.

### 6. Versionamento do coletor

O painel admin permite:

- ver a versão atual do coletor por ambiente/host
- saber quando existe versão mais nova disponível
- atualizar os arquivos do coletor nos hosts do ambiente
- retroceder para uma versão anterior

Cada deploy grava um marcador local de versão no host do coletor.

## Regras de Negócio

### Perfis de acesso

- `admin`: acesso total, inclusive painel admin.
- `technical`: operação e acesso a produção.
- `operator`: operação sem acesso a produção.

### Restrições operacionais

- `operator` não pode acessar ambientes de produção.
- em produção, start/stop em lote devem considerar todos os serviços cadastrados do ambiente, sem ignorar por prioridade.
- fora de produção, start em lote deve iniciar apenas prioridades alta e média.
- o serviço de license nunca participa de `Iniciar todos` ou `Parar todos` em nenhum ambiente; quando necessário, deve ser operado individualmente por administrador.
- operações em lote resolvem cada serviço por `nome + IP` e tratam serviços já no estado desejado como sucesso operacional, reduzindo falhas desnecessárias.
- stop/restart devem priorizar `taskkill`.

### Coletor como fonte primária

- status de serviços deve vir do coletor
- confirmação de start/stop/restart deve usar o coletor
- busca automática deve usar o coletor
- quando o coletor estiver parado/desatualizado, os serviços devem ser exibidos como `COLETOR PARADO`

### Saúde do coletor

- o coletor é considerado parado/desatualizado após a janela de tolerância configurada
- o log de saúde registra apenas transições relevantes para estado parado, evitando ruído excessivo

### Auditoria

O log registra apenas o essencial:

- login bem-sucedido
- logout bem-sucedido
- eventos operacionais relevantes

Eventos muito repetitivos são deduplicados e o arquivo de log possui retenção limitada para evitar crescimento excessivo.

## Principais Endpoints

### Autenticação

- `GET /login`
- `POST /login`
- `POST /logout`

### Operação

- `GET /`
- `GET /status`
- `POST /action`
- `GET /events`
- `GET /alerts`

### Administração

- `GET /admin`
- `GET /users`
- `POST /users`
- `PUT /users/<username>`
- `DELETE /users/<username>`
- `GET /environments`
- `POST /environments`
- `PUT /environments/<environment_id>`
- `DELETE /environments/<environment_id>`
- `POST /discover-services`
- `GET /alert-settings`
- `PUT /alert-settings`
- `GET /collector/deployments`
- `POST /collector/deployments/<environment_id>`

## Configuração

Variáveis principais:

- `APP_SECRET_KEY`
- `PROTHEUS_ADMIN_USER`
- `PROTHEUS_ADMIN_PASSWORD`
- `GAMB_FORCE_HTTPS`
- `GAMB_BEHIND_PROXY`
- `GAMB_SSL_CERT_FILE`
- `GAMB_SSL_KEY_FILE`

## Execução Local

Exemplo simples:

```powershell
py -3 app.py
```

Validação de sintaxe do backend:

```powershell
py -3 -m py_compile app.py
```

## Versionando o Coletor

Para gerar uma nova versão do coletor:

```powershell
powershell -ExecutionPolicy Bypass -File gamb-coletor\versions\new-collector-version.ps1 -SourceVersion multilingual-2026-04-16 -UseCurrentTimestamp
```

Isso cria uma nova pasta em `gamb-coletor/versions/`, pronta para deploy e rollback.

## Observações Técnicas

- o projeto é orientado a Windows
- o controle de serviços usa integração com `win32serviceutil` e utilitários nativos
- o frontend segue uma linguagem visual consistente e centrada em tema escuro
- a UI evita dependências externas críticas, inclusive com Tailwind local

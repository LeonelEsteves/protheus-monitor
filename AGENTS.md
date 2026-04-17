# Protheus Monitor (Codex)

Este reposit√≥rio √© um app **Flask** (Windows) para **monitorar e controlar servi√ßos do Windows** relacionados ao Protheus/TOTVS por ambiente, com autentica√ß√£o e painel web.

## Como o Codex deve ‚Äúlembrar‚Äù deste projeto

- **Use este `AGENTS.md` como mem√≥ria persistente do projeto** (equivalente ao `CLAUDE.md`).
- Quando o usu√°rio der **novas instru√ß√µes dur√°veis** (padr√µes, decis√µes, comandos, arquitetura, conven√ß√µes), **atualize este arquivo** antes de encerrar a tarefa, mantendo-o curto e objetivo.
- Para detalhes mais longos (log de decis√µes/comandos confirmados), mantenha tamb√©m `PROJECT_MEMORY.md` atualizado.
- Evite reler o repo inteiro: comece por aqui e s√≥ abra arquivos quando precisar de detalhes.

## Estrutura (principais arquivos)

- `app.py`: servidor Flask + regras de auth + rotas + integra√ß√£o com `win32serviceutil`.
- `templates/index.html`: painel principal (status/a√ß√µes por ambiente).
- `templates/admin.html`: painel admin (usu√°rios/ambientes).
- `templates/login.html`: tela de login.
- `users.json`: base de usu√°rios (hash de senha + role + active).
- `environments.json`: cadastro de ambientes e servi√ßos (appserver/rest/etc).
- `environments.json` (servi√ßos): `display_name`, `path_executable`, `tcp_port`, `webapp_port`, `rest_port`, `service_ip`, `console_log_file`, `priority` (`baixa`/`media`/`alta`).
- `events_log.json`: log de a√ß√µes (start/stop/restart) e alertas.
- Auto-discovery (admin): endpoint `POST /discover-services` tenta descobrir servi√ßos via PowerShell Remoting (WinRM) e ler `bin\\appserver.ini`.

## Regras de neg√≥cio (resumo)

- Autentica√ß√£o por sess√£o (`session["username"]`); usu√°rio pode ser desativado (`active: false`).
- Pap√©is: `admin` (acesso ao `/admin` e APIs de users/environments), `technical` (opera√ß√£o + acesso a produ√ß√£o) e `operator` (opera√ß√£o sem produ√ß√£o).
- A√ß√µes dispon√≠veis por servi√ßo: `start`, `stop`, `restart` (via `win32serviceutil.*`).
- Status dos ambientes √© calculado por ambiente e pode ser buscado em paralelo (`ThreadPoolExecutor`).
- Regra: `operator` n√£o pode acessar ambientes `environment_type=producao` (index/status/action filtram/bloqueiam).
- `service_ip` (quando informado) √© usado para status/a√ß√µes do servi√ßo (sobrescreve o host do ambiente).

## Configura√ß√£o / vari√°veis de ambiente (importante)

- `APP_SECRET_KEY`: segredo da sess√£o (trocar em produ√ß√£o).
- `PROTHEUS_ADMIN_USER` / `PROTHEUS_ADMIN_PASSWORD`: credenciais iniciais do admin (cria `users.json` se n√£o existir).

## Integra√ß√µes externas (opcional)

- Teams webhook e SMTP existem, mas podem estar desabilitados por configura√ß√£o vazia.

## Conven√ß√µes para mudan√ßas

- Preferir mudan√ßas **m√≠nimas** e consistentes com o estilo atual.
- N√£o quebrar o formato de `users.json` e `environments.json` (backward compatibility).
- Ao alterar HTML/JS, manter a UI funcional sem depender de bundlers (projeto simples).
- Padr√£o visual obrigat√≥rio: novas telas, modais e componentes devem seguir o mesmo layout/estilo j√° adotado no projeto (mesma linguagem visual, bordas, tipografia, espa√ßamento e comportamento em tema claro/escuro).
- Bloco de informacoes do servidor no topo do ambiente deve permanecer compacto/minimalista; usar chips curtos e barra de disco por unidade (sem texto extenso de capacidade livre no corpo principal).

- Regra adicional: exclusao de servico no formulario deve pedir confirmacao; incluir/alterar/excluir servico precisa gerar log em events_log.json.
- Tela de serviÁos monitorados deve ter filtro por nome do serviÁo e por status (RUNNING/STOPPED/etc.).
- Busca autom·tica deve registrar no log final se cada serviÁo est· rodando (SIM/N√O).
- No cadastro/ediÁ„o de ambiente, o formul·rio deve ter filtro por nome de serviÁo e sugest„o em lista (datalist) com nomes j· conhecidos.
- Gest„o de usu·rios: permitir ediÁ„o e exclus„o de usu·rio (com confirmaÁ„o e regras de seguranÁa, sem autoexclus„o).
- Consulta de status deve tentar fallback por Display Name e aliases para serviÁos de license quando o Name n„o resolve.
- Monitor por ambiente deve oferecer aÁıes em lote (Iniciar todos/Parar todos) com confirmaÁ„o prÈvia e ordem por prioridade.
- AÁ„o de parada/reinÌcio deve tentar parada graciosa e, se exceder timeout, forÁar parada (taskkill) antes de retornar erro.
- Em iniciar em lote: executar somente serviÁos de prioridade alta e mÈdia (n„o iniciar baixa).
- Parada de serviÁo deve priorizar taskkill imediato para acelerar stop/restart em ambientes com lentid„o.
- Regra operacional: parada de serviÁos (stop/restart) deve usar taskkill sempre, sem fallback para StopService.
- Em start em lote: iniciar apenas prioridades alta e mÈdia; ignorar prioridade 1.
- AÁıes de start/stop/restart devem suportar execuÁ„o assÌncrona em fila com acompanhamento por job para reduzir latÍncia da UI.
- Coletor gamb-coletor: so regravar status-servico.json quando houver mudanca real nos dados coletados; sem mudanca, manter arquivo inalterado.
- Monitor deve consumir C:\gamb-coletor\status-servico.json (local/UNC por servidor) como fonte primaria para metadados e status de servicos no /status.
- Busca automatica (/discover-services) deve priorizar C:\gamb-coletor\status-servico.json de cada servidor; usar WinRM apenas como fallback.
- Busca automatica deve usar exclusivamente o JSON do gamb-coletor (C:\gamb-coletor\status-servico.json), sem fallback por WinRM.
- Antes de qualquer acao de servico (start/stop/restart/lote/console-log), hidratar servicos do ambiente com C:\gamb-coletor\status-servico.json (gamb-coletor).
- Confirmacao de execucao das acoes start/stop/restart deve usar sempre status vindo do gamb-coletor (status-servico.json), sem consulta direta de status no Windows.
- UX de acao de servico: ao clicar Start/Stop/Restart, botao deve indicar execucao (Executando...) e ao concluir exibir status atual retornado no painel.
- Painel de status deve usar somente status do gamb-coletor (status-servico.json), sem fallback de status direto do Windows/SCM.
- Em parada em lote (stop all), nunca parar servicos de license, independentemente de perfil ou ambiente.
- Registrar em events_log.json transicoes de saude do coletor por host (COLLECTOR_HEALTH): PARADO quando sem sincronizacao recente e RODANDO quando retomar.
- Quando o coletor estiver parado/desatualizado, status dos servicos deve ser exibido como COLETOR PARADO para evitar falsa impressao operacional.
- Tempo de tolerancia para considerar coletor parado ajustado para janela confortavel (90s) no backend e UI.

- Preferencia visual: em resumo de disco, exibir percentual livre por unidade (ex.: C: 18,4% livre) e alertar "Pouco espaco em disco" quando alguma unidade estiver abaixo do limite configurado.

- Tema unico: interface deve operar somente em tema escuro; remover/evitar opcao de alternancia claro/escuro nas telas.

- Preferencia de UX: remover seletor de tema e manter somente tema escuro nas telas (login, operacao, admin e inventario).

- Cadastro de servidores removido do painel administrativo; manter apenas consulta/inventario dos servidores ja existentes.

- Busca automatica do admin deve carregar somente servicos retornados pelo JSON do gamb-coletor (sem merge com formulario e sem incluir servicos padrao nao descobertos).

- Tela de servicos monitorados deve manter a mesma ordem de cadastro dos servicos (sem reordenacao por IP/nome na exibicao).

- Auditoria: registrar em events_log.json os acessos/autenticacao dos usuarios (login, logout, negacoes) e trilha de chamadas HTTP de acoes da aplicacao com metodo, rota, status e IP.

- Auditoria vigente: registrar em events_log.json apenas entrada e saida do sistema (LOGIN e LOGOUT bem-sucedidos), sem trilha HTTP e sem logs de negacoes/invalidacoes de sessao.

- Log do coletor: registrar evento de sincronizacao apenas quando o monitor/coletor estiver sem sincronizacao recente; nao registrar retorno ao estado sincronizado.

- Painel administrativo deve oferecer rotina de alertas configuravel; tela inicial deve exibir icone/modal de alertas ao lado de logs, seguindo o mesmo padrao visual e de badge.

- Rotina de alertas: usar opcao para alertar quando o status-servico.json do coletor estiver ausente no host, em vez de monitoramento generico de sincronizacao.

- Padrao visual duravel: ao estilizar layouts, padronizar sempre para o tema dark e reutilizar o mesmo formato, modelos de tela, cores, templates, icones e demais elementos visuais ja implantados no projeto.

- Tela de cadastro de ambiente pode usar leitura mais clara e suave que o restante do dark mode; evitar cores chamativas e priorizar contraste suave, blocos distintos e secoes/itens colapsados por padrao para melhor usabilidade.

- Painel administrativo deve oferecer controle de versoes do gamb-coletor por ambiente, com atualizacao automatica dos arquivos nos hosts do ambiente e possibilidade de rollback selecionando versao anterior.

- Toda alteracao no gamb-coletor deve gerar uma nova pasta versionada em gamb-coletor/versions; manter rotina/script para snapshot automatico e rollback simples.

- Painel administrativo deve avisar quando existir versao mais nova disponivel do gamb-coletor em relacao a versao instalada no ambiente.

- Logs e alertas devem evitar repeticao; deduplicar eventos ruidosos e limitar retencao para reduzir crescimento do events_log.json e das notificacoes.

- Estrutura de dados local deve ficar centralizada em data/ para separar codigo, templates e arquivos operacionais; JSONs de usuarios, ambientes, alertas, servidores e eventos ficam em data/.

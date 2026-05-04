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
- `environments.json` (servi√ßos): `display_name`, `path_executable`, `tcp_port`, `webapp_port`, `rest_port`, `server_ip`, `console_log_file`, `priority` (`baixa`/`media`/`alta`).
- `events_log.json`: log de a√ß√µes (start/stop/restart) e alertas.
- Auto-discovery (admin): endpoint `POST /discover-services` tenta descobrir servi√ßos via PowerShell Remoting (WinRM) e ler `bin\\appserver.ini`.

## Regras de neg√≥cio (resumo)

- Autentica√ß√£o por sess√£o (`session["username"]`); usu√°rio pode ser desativado (`active: false`).
- Pap√©is: `admin` (acesso ao `/admin` e APIs de users/environments), `technical` (opera√ß√£o + acesso a produ√ß√£o) e `operator` (opera√ß√£o sem produ√ß√£o).
- A√ß√µes dispon√≠veis por servi√ßo: `start`, `stop`, `restart` (via `win32serviceutil.*`).
- Status dos ambientes √© calculado por ambiente e pode ser buscado em paralelo (`ThreadPoolExecutor`).
- Regra: `operator` n√£o pode acessar ambientes `environment_type=producao` (index/status/action filtram/bloqueiam).
- Regra vigente: n√£o usar IP por servi√ßo; status/a√ß√µes/logs usam o `server.server_ip` do `status-servico.json` de cada host (persistido como `server_ip` quando necess√°rio).
- O coletor deve exibir vers√£o expl√≠cita no BAT e gravar `server.collector_version` no `status-servico.json`; o painel pode usar esse valor como fallback ao `collector-version.json`.

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
- Cadastro de ambientes: nas linhas de servico/infra, exibir apenas Nome do servico, Display Name e Prioridade; manter campos tecnicos ocultos/preservados para salvar.
- Tela de serviÁos monitorados deve ter filtro por nome do serviÁo e por status (RUNNING/STOPPED/etc.).
- Busca autom·tica deve registrar no log final se cada serviÁo est· rodando (SIM/N√O).
- No cadastro/ediÁ„o de ambiente, o formul·rio deve ter filtro por nome de serviÁo e sugest„o em lista (datalist) com nomes j· conhecidos.
- Gest„o de usu·rios: permitir ediÁ„o e exclus„o de usu·rio (com confirmaÁ„o e regras de seguranÁa, sem autoexclus„o).
- Consulta de status deve tentar fallback por Display Name e aliases para serviÁos de license quando o Name n„o resolve.
- Monitor por ambiente deve oferecer aÁıes em lote (Iniciar todos/Parar todos) com confirmaÁ„o prÈvia e ordem por prioridade.
- Operacao em lote start/stop deve executar o BAT `gamb-bulk-services.bat` do gamb-coletor, agrupando servicos por host e registrando resultado na trilha tecnica.
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
- Confirmacao de execucao das acoes start/stop/restart deve consultar status direto no Windows/SCM, nao o status do gamb-coletor, para evitar divergencia quando o JSON ainda nao sincronizou.
- UX de acao de servico: ao clicar Start/Stop/Restart, botao deve indicar execucao (Executando...) ate o job ser confirmado; so liberar o botao apos atualizar/exibir o status confirmado retornado pelo Windows no painel.
- Painel de status deve usar somente status do gamb-coletor (status-servico.json), sem fallback de status direto do Windows/SCM.
- Em parada em lote (stop all), nunca parar servicos de license, independentemente de perfil ou ambiente.
- Registrar em events_log.json transicoes de saude do coletor por host (COLLECTOR_HEALTH): PARADO quando sem sincronizacao recente e RODANDO quando retomar.
- Quando o coletor estiver parado/desatualizado, status dos servicos deve ser exibido como COLETOR PARADO para evitar falsa impressao operacional.
- Tempo de tolerancia para considerar coletor parado ajustado para janela confortavel (180s) no backend e UI, com releitura sem cache antes de marcar stale.

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

- A pagina principal deve oferecer acesso a documentacao tecnica do sistema para todos os usuarios autenticados, usando o README.md como fonte.

- Sempre que houver novas atualizacoes tecnicas relevantes do ambiente ou do sistema, atualizar o README.md da raiz; a documentacao deve permanecer disponivel na pagina principal para todos os usuarios autenticados.

- Rotina de alertas: em ambientes de producao, qualquer servico parado deve gerar alerta critico; nos demais, manter foco em servicos de prioridade alta.

- Operacao em lote: em producao, start/stop em lote devem considerar todos os servicos cadastrados do ambiente; fora de producao, manter filtros anteriores de prioridade e preservacao de license no stop all.

- Operacao em lote: o servico de license nunca deve participar de Iniciar todos ou Parar todos em nenhum ambiente; qualquer operacao nele deve ser individual e restrita ao administrador quando aplicavel.

- Sincronizacao com o coletor deve verificar disponibilidade dos hosts do ambiente; quando um host nao responder, sinalizar servidor possivelmente desligado/inacessivel no painel e nos alertas.

- Em ambientes com multiplos hosts, a sincronizacao do coletor so deve ser considerada saudavel quando todos os hosts relevantes do ambiente estiverem online e com JSON/timestamp validos.

- Toda execucao de start/stop/restart, incluindo lote, deve gravar trilha tecnica separada em data/execution_trace.json com ambiente, host, servico, acao, resultado e erro/retorno para diagnostico futuro.

- Rotina de alertas deve ter opcao separada para alertar quando qualquer servico de producao estiver parado; essa regra nao deve ficar misturada com servicos criticos dos demais ambientes.

- Em qualquer alteracao de layout, manter padrao dark em todos os formularios, modais, filtros e campos de entrada; evitar fundos brancos ou elementos claros destoando do admin/operacao.

- Rotina de alertas deve suportar envio automatico para Teams via webhook configurado no painel administrativo, com deduplicacao para evitar repeticao de mensagens no canal corporativo.

- Segredos como webhook do Teams devem ficar em arquivo local ignorado pelo Git (data/secret_settings.json) ou variavel de ambiente; nunca versionar em data/alert_settings.json.

- Webhook de alertas deve permitir ativar/desativar, escolher dias da semana, horario ou full time, e filtrar tipos de alerta enviados ao Teams.

- Envio de alertas ao Teams deve enviar um card/mensagem separado por alerta novo, respeitando deduplicacao, severidade, dias e horario configurados.

- Contagem de Windows Updates deve considerar apenas atualizacoes de software em todo o sistema, usando filtro IsInstalled=0 and IsHidden=0 and Type='Software'; nao contar drivers/opcionais fora desse criterio.

- Sempre que houver alteracao no gamb-coletor, gerar uma nova pasta versionada em gamb-coletor/versions antes de orientar deploy, preservando rollback da versao anterior.

- Nomes de novas versoes do coletor devem ser curtos no padrao vYYYYMMDD ou vYYYYMMDD-HHMMSS; evitar nomes longos/descritivos na pasta de versoes.

- Alertas de updates enviados ao webhook devem ser separados por servidor e usar exclusivamente server_ip e windows_updates_pending do JSON sincronizado daquele coletor; ignorar hosts offline, stale ou sem payload.

- Cards do webhook/Teams devem usar Adaptive Card organizado, com icone por cenario e informacoes em campos separados para legibilidade.

- Painel administrativo deve oferecer limpeza protegida de logs operacionais, trilha tecnica e estado de deduplicacao de alertas/webhook, sem apagar usuarios, ambientes, configuracoes ou segredos.

- Campos de confirmacao, inputs e areas de digitacao em modais devem sempre usar fundo dark padronizado (#0f172a/rgba(15,23,42,0.92)), borda slate e texto claro; nunca deixar fundo branco no tema dark.

- Windows Updates por ambiente: somar apenas hosts validos/sincronizados por `server_ip`; hosts offline, sem JSON ou stale nao entram na soma e devem aparecer como N/D.
- Webhook/Teams: manter segredo fora do git, enviar alertas separados por Adaptive Card, respeitar agenda/severidade e deduplicacao.
- Webhook/Teams: para alertas gerais, nao reenviar a mesma mensagem no mesmo dia civil; permitir novo envio apenas em outro dia, mantendo a deduplicacao especial ja existente para Windows Update.
- Webhook/Teams: suportar dois webhooks (producao e homologacao) com selecao mutuamente exclusiva; somente o canal ativo deve receber mensagens.
- UX/performance: badge de alertas na tela principal deve usar resumo leve; carregar lista completa de alertas somente ao abrir o modal.
- Alertas de servico critico/parado enviados ao Teams podem exibir botao "Iniciar servico" usando link seguro do monitor; exige APP_PUBLIC_BASE_URL acessivel e confirmacao autenticada no browser.
- Coletor: toda alteracao nos arquivos do coletor deve gerar versao curta em `gamb-coletor/versions`.
- Windows Update no webhook: enviar no maximo uma vez por semana por ambiente/servidor, sempre na segunda-feira, mesmo que a quantidade de updates mude durante a semana.
- Alertas de Windows Update devem ter severidade informativa (`info`) na aplicacao e no webhook.

- Tela principal de servicos: exibir o valor bruto de windows_updates_pending vindo do JSON por host quando existir; soma/webhook continuam usando somente hosts validos/sincronizados.

- Cards de Windows Update no Teams devem ler JSON fresco por host, usar server_ip/windows_updates_pending do proprio JSON, deduplicar por server_ip e nao usar soma agregada/cache para contagem.

- Painel admin deve ter botao para envio imediato de todos os alertas elegiveis ao webhook/Teams, sem alterar agenda/tempo configurado.

- Ordenacao de servicos: tela principal e cadastro de ambientes devem exibir homologacao/desenvolvimento por display_name; producao preserva ordem original.


- Sincronizacao do coletor: considerar stale apenas quando o JSON for lido e o timestamp exceder 180s; falha temporaria de leitura do status-servico.json deve aparecer como JSON inacessivel, sem marcar servicos como COLETOR PARADO nem gerar alerta de servico parado sem sincronismo confiavel.

- Alertas de servico parado devem ignorar janelas curtas de start/restart em andamento ou concluido recentemente, para evitar falso positivo durante reinicializacao operacional.

- Teams: quando um servico critico/producao parar e depois voltar a funcionar, enviar alerta de retorno ao normal com severidade informativa (`info`), para complementar o alerta de parada.

- Busca automatica de servicos deve considerar explicitamente servicos com TSS no Name/Display Name, alem de TOTVS.

- Gamb-coletor: filtro padrao do coletor e da descoberta deve incluir TOTVS e TSS; novas versoes do coletor precisam preservar esse criterio.

- Gamb-coletor BAT: manter cabecalho fixo no console, com limpeza/redesenho por ciclo para evitar que a janela cresca visualmente durante a coleta continua.







## Snapshot estavel do coletor

Data da captura: `2026-04-16`

Arquivos versionados:
- `gamb-colector-service.bat`
- `gamb-colector-service.ps1`

Objetivo:
- preservar a versao considerada mais estavel do coletor
- permitir restauracao rapida em caso de falha futura

Como restaurar:
1. Pare o processo ou servico atual do coletor.
2. Copie estes dois arquivos para `gamb-coletor\`.
3. Inicie novamente o coletor pelo `.bat` ou pelo servico configurado.

Observacao:
- este snapshot nao altera o estado atual do ambiente; ele apenas guarda uma copia de seguranca.

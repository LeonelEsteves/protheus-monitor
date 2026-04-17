## Snapshot do coletor com suporte a multi idiomas

Data da captura:`2026-04-17'

Arquivos versionados:
- `gamb-colector-service.bat`
- `gamb-colector-service.ps1`

Objetivo:
- preservar a versao do coletor ajustada para servidores com Windows em idiomas diferentes
- evitar falha na leitura do caminho do executavel quando a saida do `sc.exe qc` muda conforme a linguagem do sistema

Diferenca principal:
- o coletor tenta primeiro obter o caminho do servico via `Win32_Service.PathName`
- se nao conseguir, usa o fallback antigo com `sc.exe qc`

Como restaurar:
1. Pare o processo ou servico atual do coletor.
2. Copie estes dois arquivos para `gamb-coletor\`.
3. Inicie novamente o coletor pelo `.bat` ou pelo servico configurado.

Como gerar uma nova versao:
1. Altere os arquivos desta versao.
2. Execute `powershell -ExecutionPolicy Bypass -File gamb-coletor\versions\new-collector-version.ps1 -SourceVersion multilingual-2026-04-17-teste -UseCurrentTimestamp`.
3. Uma nova pasta sera criada em `gamb-coletor\versions\`, pronta para deploy e rollback.


# Faxina Segura do Workspace

Data: 2026-04-19

## Escopo

Limpeza limitada a artefatos descartaveis ja ignorados pelo repositorio:

- diretorios `__pycache__`
- diretorios `.pytest_tmp*`
- diretorios `.pytest_local_tmp`
- diretorio `tests/_tmp`
- caches auxiliares de pytest dentro de `tests/_tmp`

Nao houve remocao de codigo fonte, `data/`, documentos, resultados de pesquisa nem arquivos versionados.

## O que foi removido

Resumo:

- `95` diretorios `__pycache__` removidos do workspace principal e de `.worktrees/`
- caches Python removidos de `analysis/`, `api/`, `bot/`, `config/`, `core/`, `engines/`, `launcher_support/`, `macro_brain/`, `tests/`, `tools/` e worktrees auxiliares
- nenhum arquivo versionado foi alterado pela limpeza

Impacto esperado:

- menos ruido em buscas recursivas
- menos lixo para indexacao local
- menos atrito com scans de manutencao
- reducao de poluicao visual na arvore do projeto

## O que ficou pendente por permissao

Os itens abaixo continuam no workspace porque o Windows/OneDrive retornou `AccessDenied` mesmo apos tentativa de remocao forcada:

- `.pytest_local_tmp`
- `.pytest_tmp`
- `.pytest_tmp_38722c2062f943c0ba72335b15f536e5`
- `.pytest_tmp_a86bd45620f34b93aaa999588e59c712`
- `.pytest_tmp_f5a7b20b3a054e9b9d456088b4f7e14b`
- `tests/_tmp`
- `tests/_tmp/pytest-cache-files-o3snt7zi`

Observacoes:

- `tests/_tmp` aparece com `ReparsePoint` no ambiente atual
- os diretorios `.pytest_*` restantes estao vazios no `dir`, mas seguem protegidos no nivel do sistema
- isso aponta mais para lock/permissao do ambiente do que para conteudo util do projeto

## Estado final da migracao de `core/*`

O repositorio ainda mantem `32` shims de compatibilidade em `core/`, redirecionando imports antigos para os novos subpacotes:

- `core.data.*`
- `core.ops.*`
- `core.ui.*`
- `core.risk.*`
- `core.analysis.*`
- `core.arb.*`

Esses shims nao aparecem mais no codigo executavel via imports legacy.
Ao final desta sessao, o grep de `core.<shim_legacy>` em codigo ativo
retornou zero referencias, restando apenas um comentario historico em
`launcher.py` mencionando `core.proc.ENGINES`.

## Melhorias aplicadas

Foi feita migracao mecanica de imports para os destinos finais:

- `core.ops.*`
- `core.data.*`
- `core.ui.*`
- `core.risk.*`
- `core.analysis.*`
- `core.arb.*`

Areas migradas:

- launcher e CLI principal
- engines principais e engines auxiliares
- bot Telegram
- API e scripts de manutencao
- dashboards e viewers
- batteries e ferramentas de relatorio
- smoke / replay / arquivos de apoio

Objetivo atingido:

- remover dependencia operacional dos shims de `core/*`
- reduzir risco de import errado
- preparar a remocao futura dos wrappers de compatibilidade

## Alinhamento com outros agentes

Durante a sessao, os arquivos que ja apareciam modificados foram tratados
com patches minimos e localizados, restritos as linhas de import quando
necessario. Nao houve limpeza de diffs alheios nem reversao de trabalho
em andamento.

## Risco atual

Nao ha indicio de "arquivo morto perigoso" no codigo ativo nesta faxina. O risco mais concreto continua sendo:

- workspace sujo por temporarios presos em permissao
- shims de `core/` ainda existem e agora podem ser removidos em outra etapa
- existe um comentario residual em `launcher.py` mencionando um caminho antigo

## Aberto

Itens realmente abertos ao encerrar:

- diretorios temporarios presos por permissao:
  `.pytest_local_tmp`, `.pytest_tmp`, `.pytest_tmp_*`, `tests/_tmp`
- um comentario em `launcher.py` com texto legado (`core.proc.ENGINES`)
- os shims de compatibilidade em `core/` ainda nao foram deletados

## Encerramento

A faxina segura do workspace foi executada, a migracao mecanica dos imports
legacy foi concluida e o repositorio ficou sem referencias operacionais a
`core.<shim_legacy>`.

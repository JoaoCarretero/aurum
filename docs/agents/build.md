# BUILD - Implementation

**Foco:** implementar engines, features e fixes aprovados sem expandir escopo.

## Entradas
- Spec aprovada, plano de arquivos e contrato de teste.
- Padroes existentes do repo e restricoes de lane em `AGENTS.md`.

## Saidas
- Patch pequeno e revisavel.
- Teste focado no comportamento novo ou risco tocado.
- Nota de arquivos alterados e comandos de verificacao.

## Regras
- CORE e `config/keys.json` ficam fora do escopo sem aprovacao explicita do Joao.
- Usar padroes locais antes de criar abstracao nova.
- Nao mexer em mudancas de outros agentes fora do escopo.

## Pausar Quando
- Spec nao indicar comportamento esperado.
- A implementacao exigir mudanca protegida.

## Edit
Arquivo editavel pelo Research Desk launcher. Contexto completo: `AGENTS.md` no root.

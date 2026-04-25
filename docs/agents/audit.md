# AUDIT - Integrity Gate

**Foco:** gate final entre `stage=research` e `live_ready`.

## Entradas
- Spec aprovada, diff final, backtests, walk-forward, custos e logs de execucao.
- Reviews anteriores e metodologia anti-overfit.

## Saidas
- Veredito `VALIDATED`, `CONDITIONAL` ou `REJECTED`.
- Blocos de evidencia: conformance, baseline, walk-forward, sensitivity, cost stress e lookahead.
- Caminho do audit em `docs/audits/engines/YYYY-MM-DD_audit_<engine>.md` quando aplicavel.

## Regras
- Auditar realidade, nao intencao.
- Gate numerico vence estetica de codigo.
- Se dado faltar, marcar `PARTIAL` ou `CONDITIONAL`; nao inferir sucesso.

## Pausar Quando
- REVIEW ainda nao emitiu `SHIP`.
- Dataset ou artefato essencial estiver indisponivel.

## Edit
Arquivo editavel pelo Research Desk launcher. Contexto completo: `AGENTS.md` no root.

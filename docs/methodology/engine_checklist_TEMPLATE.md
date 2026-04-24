# Engine Validation Checklist — <ENGINE_NAME>

> Copiar este template pra `docs/engines/<engine>/checklist.md` ANTES de começar.
> Preencher **antes de abrir qualquer código**.
> Commit antes de rodar a primeira config.

---

## Passo 1 — Hipótese mecânica

### Fenômeno de mercado
<!-- 1 parágrafo: que padrão real existe? -->

### Mecanismo
<!-- 1 parágrafo: microestrutura? comportamento? estrutural? -->

### Precedente acadêmico
<!-- papers, autores, mecanismo conhecido -->

### Falsificação
<!-- o que provaria que NÃO funciona? -->

---

## Passo 2 — Split (hardcoded)

```
TRAIN_END = "YYYY-MM-DD"
TEST_END  = "YYYY-MM-DD"
HOLDOUT   = "YYYY-MM-DD" até hoje
```

- [ ] Datas commitadas em `engines/<engine>.py`
- [ ] Train_end é ANTES de qualquer iter_N WINNER em `config/params.py`

---

## Passo 3 — Grid pré-registrado

**Budget: N configs máximo.**

| # | Param1 | Param2 | ... |
|---|---|---|---|
| 1 |  |  |  |
| 2 |  |  |  |

- [ ] Lista completa acima
- [ ] Commit feito ANTES de rodar config #1

---

## Passo 4 — Resultados train

Preencher após rodar os N configs em train.

| # | Sharpe | Sortino | MDD | Trades |
|---|---|---|---|---|
| 1 |  |  |  |  |
| ... |  |  |  |  |

- Best Sharpe: 
- Std Sharpe: 

---

## Passo 5 — DSR

- n_trials: 
- sharpe_best: 
- sharpe_std: 
- DSR p-value: 
- **Passou (p > 0.95)?** SIM / NÃO

Se NÃO → **ARQUIVA O ENGINE**. Preencher `archived.md` com motivo.

---

## Passo 6 — Top-3 em test

| rank | config | sharpe_train | sharpe_test | sortino_test |
|---|---|---|---|---|
| 1 |  |  |  |  |
| 2 |  |  |  |  |
| 3 |  |  |  |  |

- Pior Sharpe do top-3 em test: 
- **Passou (> 1.0)?** SIM / NÃO

Se NÃO → **ARQUIVA**.

---

## Passo 7 — Holdout

Config escolhido (pior-de-top3): 

- Sharpe holdout: 
- **Passou (> 0.8)?** SIM / NÃO

Se NÃO → **ARQUIVA**.

---

## Passo 8 — Paper forward

- Start: 
- End (30-60 dias depois): 
- Sharpe paper: 
- **Passou (> 50% holdout)?** SIM / NÃO

Se SIM → **candidato a FROZEN**. Juntar evidência e abrir PR.
Se NÃO → **ARQUIVA**.

---

## Decisão final

- [ ] FROZEN (passou tudo)
- [ ] ARQUIVADO (falhou em etapa X)
- [ ] Motivo: <!-- -->

# PHI Overfit Follow-up — 2026-04-17

## TL;DR (revisão 2026-04-17 18:30)

O "edge" anteriormente celebrado nesta página (Sharpe 7.2–9.4 em 3 janelas) era
artefato de trades com geometria inválida — setups onde `entry` abria do lado
errado do stop, criando "wins" espúrios de mesma barra. Com o gate de
integridade geométrica (`levels_geometry_ok` + `infer_executable_direction`)
aplicado, o edge colapsa em **todas** as três janelas testadas:

| Janela                  | Pré-gate (artefato) | Pós-gate (honesto)           |
|-------------------------|----------------------|------------------------------|
| `stagec_like` 180d rec  | 237 trades · S 7.23  | 83 trades · S -0.69 · WR 36% |
| `stagec_like` 180d hist | 217 trades · S 9.10  | 62 trades · S -6.10 · WR 18% |
| `stagec_like` 365d rec  | 537 trades · S 9.38  | 164 trades · S -1.94 · WR 30%|

**Recomendação:** Pela regra de parada do protocolo anti-overfit
(`docs/methodology/anti_overfit_protocol.md`), PHI deve ser **arquivado** sem
reformulação iterativa. A tese original não sobrevive ao teste físico mais
básico (geometria dos níveis).

## Scope da investigação original

Validação do `PHI` em majors (`BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT`)
após endurecimento de terminal/backtest. Objetivo: determinar se os bons
números recentes sobrevivem a janelas deslocadas e ao audit existente.

## Configs testadas

- `majors_candidate`
  - `cluster_min_confluences=1`
  - `omega_phi_entry=0.382`
- `stagec_like`
  - `cluster_min_confluences=1`
  - `adx_min=10.0`
  - `ema200_distance_atr=0.382`
  - `wick_ratio_min=0.382`
  - `omega_phi_entry=0.382`

## O que mudou entre rodagens

Entre as rodagens das 13:10 e 13:37 o engine ganhou dois guards:

- `levels_geometry_ok(entry, levels, direction)` — exige que os níveis
  respeitem a ordem econômica: long → `sl < entry < tp1 < tp2 < tp3`; short
  → ordem inversa.
- `infer_executable_direction(row, entry)` — rejeita setups cuja geometria
  admite ambas as direções (ambígua) ou nenhuma (inválida).

Ambos os guards são **corretos**. Um long aberto abaixo do stop não é uma
trade: é ruído de fixture. Antes do guard, esses casos contaminavam o
resultado com "wins" de mesma barra (o preço imediatamente "saía" do nível
na direção oposta à alegada do trade).

## Números honestos (pós-gate, com `macro_bias` propagado)

### `stagec_like` — 180d recent (terminando 2026-04-17)

- Total: 83 trades · WR 36.14% · PF 0.880 · Sharpe -0.692 · MaxDD 0.25%
- Total PnL: -$7.94
- Overfit audit: **1/6 PASS · 5 FAIL**
  - A walk-forward: FAIL — 4/5 janelas com expectativa negativa
  - B sensitivity: PASS (mas sobre edge negativo)
  - C concentration: FAIL — remover BNBUSDT deixa PnL negativo
  - D regime: FAIL — nenhum regime com PnL positivo
  - E temporal: FAIL — 2ª metade com expectativa negativa (decay forte)
  - F slippage: FAIL — breakeven 2bp

### `stagec_like` — 180d displaced ending 2025-07-01

- Total: 62 trades · WR 17.74% · PF 0.293 · Sharpe -6.104 · MaxDD 0.48%
- Total PnL: -$46.19
- Overfit audit: **2/6 PASS · 4 FAIL**
  - A walk-forward: FAIL — 4/5 janelas com expectativa negativa
  - B sensitivity: PASS (sobre edge negativo)
  - C concentration: FAIL — remover XRPUSDT deixa PnL negativo
  - D regime: FAIL — nenhum regime com PnL positivo
  - E temporal: FAIL
  - F slippage: PASS com breakeven 10bp — subproduto de perdas, não sinal de saúde

### `stagec_like` — 365d recent

- Total: 164 trades · WR 30.49% · PF 0.697 · Sharpe -1.937 · MaxDD 0.49%
- Total PnL: -$41.80
- Overfit audit: **1/6 PASS · 5 FAIL**
  - A walk-forward: FAIL — 4/5 janelas com expectativa negativa
  - B sensitivity: PASS (sobre edge negativo)
  - C concentration: FAIL — remover ETHUSDT deixa PnL negativo
  - D regime: FAIL — nenhum regime com PnL positivo
  - E temporal: FAIL
  - F slippage: FAIL — breakeven 4bp

## Interpretação

O que era apresentado como "edge real sobrevivendo a deslocamento" era, de
fato, o mesmo bug geométrico aparecendo nas duas janelas. Ambos os períodos
compartilhavam a característica de produzir muitos setups com entry fora do
intervalo `sl..tp1`, que a lógica de exit interpretava como wins de mesma
barra.

Corrigida a física, as três janelas revelam uma estratégia sem edge:

- **Sinal inexistente em todos os regimes** (teste D FAIL — primeira vez que
  o teste de regime roda pra PHI, agora que `macro_bias` é tagged).
- **Concentração fatal** — qualquer símbolo removido vira PnL negativo.
- **Decay forte** — 2ª metade do período pior que a 1ª em todas as janelas.
- **Walk-forward colapsa** — 4/5 janelas com expectativa negativa.

## Trabalho feito nesta sessão

- Tag `macro_bias` (BULL/BEAR/CHOP) em `scan_symbol` — teste D sai de SKIP.
- Parâmetro `min_target_bp` (gate físico contra alvos muito estreitos vs.
  friction de execução) — implementado e coberto por testes, mas tornou-se
  irrelevante frente à descoberta principal.
- Normalizer `phi_overfit_audit.py` propaga `macro_bias`.
- Testes de integração para `scan_symbol` (`test_scan_symbol_tags_macro_bias`,
  `test_scan_symbol_min_target_bp_*`).
- Reproduzidas as 3 janelas pós-gate para documentação honesta.

## Próximo passo

Pelo protocolo anti-overfit, 3 engines consecutivos arquivados → **pausar e
revisar método**, não reformular. PHI deve entrar para a lista ARQUIVADO:

1. Registrar em `config/engines.py` como arquivado (ou remover do registry).
2. Atualizar memory `project_engine_status_2026_04_16_oos.md`.
3. Atualizar registry em `CLAUDE.md` (PHI: 🗄️ ARQUIVADO — edge era artefato
   de geometria inválida).

Reformular PHI requer:
- Mecanismo escrito *antes* de abrir código.
- Motivação defensável pra *por que* a nova tese resolveria a ausência de
  edge pós-gate, não só empilhar parâmetros.
- Split train/test/holdout prévio.

Sem isso, é fishing expedition.

## Artefatos

Runs persistidos em:

- `data/phi/2026-04-17_1812/` (180d recent postfix)
- `data/phi/stagec_like_180d_hist_postfix/2026-04-17_1818/` (180d displaced)
- `data/phi/stagec_like_365d_postfix/2026-04-17_1821/` (365d recent)

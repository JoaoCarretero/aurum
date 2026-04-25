# Backtest HTML — polish visual

**Data:** 2026-04-17
**Arquivo alvo:** `analysis/report_html.py` (único — serve todos os engines)
**Motivo:** report HTML atual parece "quadrado" (blocos repetitivos, mesmo peso) e métricas ficam "muito pra esquerda" (cards com `text-align: left` default, valores curtos sobra buraco).

## Escopo

Polimento CSS + pequenos ajustes HTML em `analysis/report_html.py`. Sem tocar em cálculo, dados ou estrutura de JSON. Nenhuma mudança em engines, logs ou métricas de fato.

## Mudanças

### 1. Alinhamento (resolver "muito pra esquerda")

- `.metric-card` → `text-align: center`, `display: flex; flex-direction: column; justify-content: center`, `min-height` pra uniformidade
- `.summary-balance` → `text-align: center`; `.summary-balance-main` com `justify-content: center`
- `.summary-balance-main` valor final sobe de 36px → 48px; valor inicial (muted) cai pra 26px (hierarquia clara)
- `.summary-verdict` vira chip pill: `inline-flex`, `border-radius: 999px`, borda `currentColor`, bolinha glow antes do texto; wrapper com `text-align: center`

### 2. Anti-quadrado (ritmo visual)

- `.metric-card::before` — hairline horizontal dourada no topo (gradient-masked, opacity 0.4) → pontua cada card sem borda pesada
- `.summary-card::before` — mesma hairline dourada, mais longa, no topo do card principal
- `.report-section` — background mais leve (0.82 → 0.55), borda mais sutil (0.06 → 0.035), padding maior (22/24 → 28/30), margin maior (22 → 26)
- `.summary-card` padding sobe (24/26 → 36/32), border-radius 22 → 24

### 3. Respiração

- `.strip-grid` gap 12 → 16
- `.summary-grid` gap 12 → 16
- `.hero` margin-bottom 24 → 28

## Fora do escopo

- Reestruturar seções (permanecem na mesma ordem)
- Mexer em SVGs (equity, MC)
- Logs `mercurio.log`
- Métricas novas ou remoção de existentes
- Dashboard 2-colunas (approach C descartado)

## Validação

- Regenerar HTML do run mais recente do JUMP e abrir
- Nenhum smoke test necessário (CSS puro + HTML inerte)
- Verificar visualmente: cards centrados, verdict em pill, menos "blocos iguais"

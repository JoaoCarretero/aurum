# DE SHAW Pairs Mean-Reversion Grid

> Registro disciplinado para continuar a lane de mean reversion via spread,
> não via preço isolado.
> Data de registro: 2026-04-18.
> Budget fechado: 6 configs.

## Hipótese mecânica

Se mean reversion não aparece no preço single-asset, a próxima família
plausível é no spread entre ativos relacionados. O edge vem de divergência
relativa temporária entre pares cointegrados, não de "preço longe da EMA".

## Conflito a resolver

O repo hoje tem sinais contraditórios:
- `docs/days/2026-04-15.md` diz que DE SHAW em 1h/bluechip não tem edge
- o header atual de `engines/deshaw.py` diz que há configuração candidata

Esta bateria existe para resolver esse conflito com uma grade única.

## Tese fixa

- Engine: `DE SHAW`
- Família: pairs / spread mean reversion
- Universo: `bluechip`
- Timeframe: `1h`
- Horizonte: `1095d`

## O que pode variar

- `z_entry`
- `pvalue`
- `hl_max`
- `max_hold`

## O que não pode variar

- Nada de trocar universo ou TF no meio
- Nada de adicionar filtros fora do que a engine já expõe
- Nada de inserir variantes extras após começar a bateria

## Filtros mínimos

- `trades >= 200`
- `sharpe > 0`
- `roi > 0`

## Grid pré-registrado

| Variant | z_entry | z_exit | z_stop | pvalue | hl_max | max_hold | size_mult |
|---|---:|---:|---:|---:|---:|---:|---:|
| DS00_baseline_recommended | 3.0 | 0.0 | 3.5 | 0.15 | 300 | default | 1.0 |
| DS01_p010 | 3.0 | 0.0 | 3.5 | 0.10 | 300 | default | 1.0 |
| DS02_p005 | 3.0 | 0.0 | 3.5 | 0.05 | 300 | default | 1.0 |
| DS03_hl200 | 3.0 | 0.0 | 3.5 | 0.15 | 200 | default | 1.0 |
| DS04_hold_shorter | 3.0 | 0.0 | 3.5 | 0.15 | 300 | 72 | 1.0 |
| DS05_z35 | 3.5 | 0.0 | 4.0 | 0.15 | 300 | default | 1.0 |

## Regra de parada

- Se zero variants passarem os filtros mínimos, mean reversion via pairs
  nesta implementação fica rejeitada por ora.
- Se 1-2 variants passarem, elas viram candidatas para etapa seguinte
  de validação fora da amostra.

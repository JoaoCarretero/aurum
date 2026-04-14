"""AURUM Macro Brain — autonomous CIO layer (weeks-months horizon).

NÃO interfere com trade engines. Separate P&L, decision loop, account.

Pipeline:
  data_ingestion → ml_engine.features → ml_engine.regime →
  thesis.generator → position.manager → pnl_ledger

Shared infra (read-only): core.exchange_api, core.audit_trail,
core.risk_gates, core.connections.
"""
__version__ = "0.1.0"

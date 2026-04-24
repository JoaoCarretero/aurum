"""Tests do artifact_linking — pure functions sem Tk."""
from __future__ import annotations

import time

from launcher_support.research_desk.artifact_linking import (
    LinkedChain,
    backtest_command_for,
    chains_for_agent,
    detect_engine,
    link_artifacts,
    normalize_stem,
)
from launcher_support.research_desk.artifact_scanner import ArtifactEntry


def _art(
    agent: str = "SCRYER",
    kind: str = "spec",
    title: str = "phi-fib",
    mtime: float | None = None,
) -> ArtifactEntry:
    return ArtifactEntry(
        agent_key=agent, kind=kind, title=title,
        path=f"docs/{kind}s/{title}.md",
        mtime_epoch=mtime if mtime is not None else time.time(),
        is_markdown=(kind != "branch"),
    )


# ── normalize_stem ────────────────────────────────────────────────


def test_normalize_stem_lowercases() -> None:
    assert normalize_stem("PHI_FIB") == "phi-fib"


def test_normalize_stem_collapses_whitespace() -> None:
    assert normalize_stem("phi  fib  v2") == "phi-fib-v2"


def test_normalize_stem_strips_outer_hyphens() -> None:
    assert normalize_stem("-phi-fib-") == "phi-fib"


def test_normalize_stem_idempotent() -> None:
    once = normalize_stem("phi_FIB v2")
    twice = normalize_stem(once)
    assert once == twice == "phi-fib-v2"


def test_normalize_stem_strips_brackets_and_punct() -> None:
    # Titulos livres com brackets precisam virar stem limpo senao
    # detect_engine nao acha o prefixo
    assert normalize_stem("[PHI] fib_v2") == "phi-fib-v2"
    assert normalize_stem("(renaissance) v3!") == "renaissance-v3"
    # Engine detection funciona apos normalize
    assert detect_engine(normalize_stem("[PHI] fib")) == "PHI"


# ── detect_engine ─────────────────────────────────────────────────


def test_detect_engine_exact_match() -> None:
    assert detect_engine("phi") == "PHI"
    assert detect_engine("citadel") == "CITADEL"


def test_detect_engine_prefix_match() -> None:
    assert detect_engine("phi-fib") == "PHI"
    assert detect_engine("citadel-regime") == "CITADEL"


def test_detect_engine_no_match() -> None:
    assert detect_engine("unknown-strategy") is None


def test_detect_engine_multi_word() -> None:
    assert detect_engine("jane-street-v2") == "JANE_STREET"


# ── link_artifacts ────────────────────────────────────────────────


def test_link_spec_and_review_makes_chain() -> None:
    artifacts = [
        _art(agent="SCRYER", kind="spec", title="phi-fib"),
        _art(agent="ARBITER", kind="review", title="phi-fib"),
    ]
    chains = link_artifacts(artifacts)
    assert len(chains) == 1
    chain = chains[0]
    assert chain.stem == "phi-fib"
    assert chain.spec is not None
    assert chain.review is not None
    assert chain.branch is None
    assert chain.is_complete is False


def test_full_chain_spec_review_branch() -> None:
    artifacts = [
        _art(agent="SCRYER", kind="spec", title="phi-fib"),
        _art(agent="ARBITER", kind="review", title="phi-fib"),
        _art(agent="ARTIFEX", kind="branch", title="phi-fib"),
    ]
    chains = link_artifacts(artifacts)
    assert len(chains) == 1
    assert chains[0].is_complete


def test_single_artifact_not_chained() -> None:
    artifacts = [_art(kind="spec", title="orphan-spec")]
    chains = link_artifacts(artifacts)
    assert chains == []


def test_different_stems_different_chains() -> None:
    artifacts = [
        _art(kind="spec", title="phi-fib"),
        _art(kind="review", title="phi-fib"),
        _art(kind="spec", title="citadel-tune"),
        _art(kind="review", title="citadel-tune"),
    ]
    chains = link_artifacts(artifacts)
    assert len(chains) == 2


def test_chain_engine_detected() -> None:
    artifacts = [
        _art(kind="spec", title="phi-fib"),
        _art(kind="review", title="phi-fib"),
    ]
    chain = link_artifacts(artifacts)[0]
    assert chain.engine == "PHI"


def test_chains_ordered_by_latest_mtime() -> None:
    artifacts = [
        _art(kind="spec", title="old", mtime=100),
        _art(kind="review", title="old", mtime=200),
        _art(kind="spec", title="new", mtime=1000),
        _art(kind="review", title="new", mtime=1100),
    ]
    chains = link_artifacts(artifacts)
    assert chains[0].stem == "new"
    assert chains[1].stem == "old"


def test_chain_normalizes_title_match() -> None:
    # Titulos com case/separator diferentes ainda devem linkar
    artifacts = [
        _art(kind="spec", title="PHI_FIB"),
        _art(kind="review", title="phi-fib"),
    ]
    chains = link_artifacts(artifacts)
    assert len(chains) == 1


# ── chains_for_agent ──────────────────────────────────────────────


def test_chains_for_agent_filters_by_kind() -> None:
    artifacts = [
        _art(kind="spec", title="phi-fib"),
        _art(kind="review", title="phi-fib"),
        _art(kind="branch", title="citadel-tune"),
        _art(kind="audit", title="citadel-tune"),
    ]
    chains = link_artifacts(artifacts)

    scryer_chains = chains_for_agent(chains, "SCRYER")  # spec
    artifex_chains = chains_for_agent(chains, "ARTIFEX")  # branch
    arbiter_chains = chains_for_agent(chains, "ARBITER")  # review

    assert len(scryer_chains) == 1  # phi-fib tem spec
    assert len(artifex_chains) == 1  # citadel tem branch
    assert len(arbiter_chains) == 1


def test_chains_for_unknown_agent_empty() -> None:
    artifacts = [
        _art(kind="spec", title="x"),
        _art(kind="review", title="x"),
    ]
    chains = link_artifacts(artifacts)
    assert chains_for_agent(chains, "NOBODY") == []


# ── backtest_command_for ──────────────────────────────────────────


def test_backtest_cmd_with_detected_engine() -> None:
    chain = LinkedChain(stem="phi-fib", engine="PHI")
    cmd = backtest_command_for(chain)
    assert "engines/phi.py" in cmd
    assert "--tag phi-fib" in cmd
    assert cmd.startswith("python")


def test_backtest_cmd_no_engine_is_comment() -> None:
    chain = LinkedChain(stem="unknown-stem")
    cmd = backtest_command_for(chain)
    assert cmd.startswith("#")

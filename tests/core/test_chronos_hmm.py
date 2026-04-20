"""Tests for the Gaussian HMM regime layer (core/chronos.py).

TDD RED: these tests are written BEFORE the implementation exists.
They must fail first, then guide the minimal implementation.
"""
import numpy as np
import pandas as pd
import pytest


# ══════════════════════════════════════════════════════════════
#  Synthetic data generator
# ══════════════════════════════════════════════════════════════
def _generate_hmm_sequence(n=1000, seed=0, easy=False):
    """Generate a sequence from a known 3-state Gaussian HMM.

    ``easy=True`` widens the state-mean separation so classification
    becomes reliably above chance. The default (hard) case reflects
    realistic crypto return noise where Bayes error is high.

    Returns (observations, true_states, true_means, true_stds, true_transmat).
    """
    rng = np.random.default_rng(seed)
    if easy:
        true_means = np.array([-0.010, 0.000, 0.010])
        true_stds = np.array([0.004, 0.003, 0.004])
    else:
        true_means = np.array([-0.0025, 0.0000, 0.0025])
        true_stds = np.array([0.0150, 0.0060, 0.0120])
    A = np.array([
        [0.95, 0.03, 0.02],
        [0.04, 0.92, 0.04],
        [0.02, 0.03, 0.95],
    ])
    pi = np.array([1/3, 1/3, 1/3])

    states = np.zeros(n, dtype=int)
    obs = np.zeros(n)
    states[0] = rng.choice(3, p=pi)
    obs[0] = rng.normal(true_means[states[0]], true_stds[states[0]])
    for t in range(1, n):
        states[t] = rng.choice(3, p=A[states[t-1]])
        obs[t] = rng.normal(true_means[states[t]], true_stds[states[t]])
    return obs, states, true_means, true_stds, A


@pytest.fixture(scope="module")
def fitted_univariate_hmm():
    from core.chronos import GaussianHMMNp

    obs, *_ = _generate_hmm_sequence(n=350, seed=1)
    X = obs.reshape(-1, 1)
    model = GaussianHMMNp(n_states=3, random_state=42, n_iter=20)
    model.fit(X)
    return X, model


@pytest.fixture(scope="module")
def enriched_regime_df():
    from core.chronos import enrich_with_regime

    rng = np.random.default_rng(42)
    n = 320
    ret = rng.normal(0, 0.01, n)
    close = 100 * np.exp(np.cumsum(ret))
    df = pd.DataFrame({
        "time": pd.date_range("2024-01-01", periods=n, freq="15min"),
        "open": close,
        "high": close * (1 + 0.001),
        "low": close * (1 - 0.001),
        "close": close,
        "vol": rng.uniform(1000, 5000, n),
        "tbb": rng.uniform(500, 2500, n),
    })
    return enrich_with_regime(df)


# ══════════════════════════════════════════════════════════════
#  GaussianHMMNp — numpy-pure Gaussian HMM
# ══════════════════════════════════════════════════════════════
class TestGaussianHMMNp:
    def test_posteriors_sum_to_one(self, fitted_univariate_hmm):
        X, model = fitted_univariate_hmm
        posts = model.predict_proba(X)
        assert posts.shape == (len(X), 3)
        np.testing.assert_allclose(posts.sum(axis=1), 1.0, atol=1e-6)

    def test_transition_matrix_rows_normalized(self, fitted_univariate_hmm):
        _, model = fitted_univariate_hmm
        np.testing.assert_allclose(model.transmat_.sum(axis=1), 1.0, atol=1e-6)
        assert (model.transmat_ >= 0).all()

    def test_start_prob_normalized(self, fitted_univariate_hmm):
        _, model = fitted_univariate_hmm
        assert abs(model.startprob_.sum() - 1.0) < 1e-6
        assert (model.startprob_ >= 0).all()

    def test_recovers_state_means_ordering_on_synthetic_data(self):
        """Recovered means must preserve the bear < chop < bull ordering.
        Absolute parameter recovery is not guaranteed by EM with noise —
        what matters is that the three states are separated and ordered."""
        from core.chronos import GaussianHMMNp
        obs, _, true_means, *_ = _generate_hmm_sequence(n=1400, seed=0)
        X = obs.reshape(-1, 1)
        model = GaussianHMMNp(n_states=3, random_state=42, n_iter=35)
        model.fit(X)

        recovered = np.sort(model.means_.flatten())
        assert recovered[0] < recovered[1] < recovered[2], \
            f"states not separated: {recovered}"
        # Bear should be clearly negative, bull clearly positive
        assert recovered[0] < 0, f"bear mean not negative: {recovered[0]}"
        assert recovered[2] > 0, f"bull mean not positive: {recovered[2]}"
        # Separation between bear and bull should be at least the true separation
        true_sep = true_means.max() - true_means.min()
        recovered_sep = recovered[2] - recovered[0]
        assert recovered_sep >= 0.5 * true_sep, \
            f"separation too small: {recovered_sep} vs {true_sep}"

    def test_classifies_synthetic_regimes_better_than_chance(self):
        """On well-separated synthetic data the HMM must classify hidden
        states at well above chance. 70% is a conservative threshold
        (chance = 33%)."""
        from core.chronos import GaussianHMMNp
        from itertools import permutations
        obs, true_states, *_ = _generate_hmm_sequence(n=1400, seed=0, easy=True)
        X = obs.reshape(-1, 1)
        model = GaussianHMMNp(n_states=3, random_state=42, n_iter=45)
        model.fit(X)
        pred = model.predict(X)

        best_acc = 0.0
        for perm in permutations(range(3)):
            mapped = np.array([perm[s] for s in pred])
            acc = (mapped == true_states).mean()
            best_acc = max(best_acc, acc)
        assert best_acc >= 0.70, f"classification accuracy {best_acc:.2%} < 70%"

    def test_means_shape_for_multivariate(self):
        from core.chronos import GaussianHMMNp
        rng = np.random.default_rng(0)
        X = rng.normal(0, 0.01, (500, 2))  # 2 features
        model = GaussianHMMNp(n_states=3, random_state=42, n_iter=20)
        model.fit(X)
        assert model.means_.shape == (3, 2)
        assert model.transmat_.shape == (3, 3)

    def test_handles_short_sequence_without_crash(self):
        from core.chronos import GaussianHMMNp
        X = np.array([[0.001], [0.002], [-0.001], [0.0], [0.0005]])
        model = GaussianHMMNp(n_states=3, random_state=42, n_iter=10)
        model.fit(X)
        posts = model.predict_proba(X)
        assert posts.shape == (5, 3)
        assert np.isfinite(posts).all()

    def test_predict_returns_valid_state_indices(self, fitted_univariate_hmm):
        X, model = fitted_univariate_hmm
        states = model.predict(X)
        assert states.shape == (len(X),)
        assert states.min() >= 0
        assert states.max() < 3

    def test_deterministic_with_same_seed(self):
        from core.chronos import GaussianHMMNp
        obs, *_ = _generate_hmm_sequence(n=500, seed=5)
        X = obs.reshape(-1, 1)
        m1 = GaussianHMMNp(n_states=3, random_state=42, n_iter=20).fit(X)
        m2 = GaussianHMMNp(n_states=3, random_state=42, n_iter=20).fit(X)
        np.testing.assert_allclose(m1.means_, m2.means_)
        np.testing.assert_allclose(m1.transmat_, m2.transmat_)


# ══════════════════════════════════════════════════════════════
#  enrich_with_regime — high-level wrapper used by all engines
# ══════════════════════════════════════════════════════════════
class TestEnrichWithRegime:
    def _make_df(self, n=500, seed=42):
        rng = np.random.default_rng(seed)
        ret = rng.normal(0, 0.01, n)
        close = 100 * np.exp(np.cumsum(ret))
        time = pd.date_range("2024-01-01", periods=n, freq="15min")
        return pd.DataFrame({
            "time": time,
            "open": close,
            "high": close * (1 + 0.001),
            "low": close * (1 - 0.001),
            "close": close,
            "vol": rng.uniform(1000, 5000, n),
            "tbb": rng.uniform(500, 2500, n),
        })

    def test_adds_required_columns(self, enriched_regime_df):
        out = enriched_regime_df
        required = [
            "hmm_regime", "hmm_regime_label",
            "hmm_prob_bull", "hmm_prob_bear", "hmm_prob_chop",
            "hmm_confidence",
        ]
        for col in required:
            assert col in out.columns, f"missing column: {col}"

    def test_regime_labels_are_valid_strings(self, enriched_regime_df):
        out = enriched_regime_df
        valid = {"BULL", "BEAR", "CHOP"}
        labels = set(out["hmm_regime_label"].dropna().unique())
        assert labels.issubset(valid), f"invalid labels: {labels - valid}"
        # On 500 candles we expect at least ONE regime label assigned
        assert len(labels) >= 1

    def test_probs_sum_to_one_where_finite(self, enriched_regime_df):
        out = enriched_regime_df
        probs = out[["hmm_prob_bull", "hmm_prob_bear", "hmm_prob_chop"]].values
        total = np.nansum(probs, axis=1)
        mask = np.isfinite(probs).all(axis=1)
        assert mask.sum() > 0, "no finite probability rows"
        np.testing.assert_allclose(total[mask], 1.0, atol=1e-5)

    def test_confidence_is_max_of_three_probs(self, enriched_regime_df):
        out = enriched_regime_df
        probs = out[["hmm_prob_bull", "hmm_prob_bear", "hmm_prob_chop"]].values
        mask = np.isfinite(probs).all(axis=1)
        expected = np.nanmax(probs[mask], axis=1)
        actual = out["hmm_confidence"].values[mask]
        np.testing.assert_allclose(actual, expected, atol=1e-6)

    def test_confidence_in_valid_range(self, enriched_regime_df):
        out = enriched_regime_df
        conf = out["hmm_confidence"].dropna().values
        assert (conf >= 1/3 - 1e-6).all(), "confidence below chance"
        assert (conf <= 1 + 1e-6).all(), "confidence above 1"

    def test_idempotent_if_columns_exist(self, enriched_regime_df):
        """Calling twice must not retrain or change values."""
        from core.chronos import enrich_with_regime
        out1 = enriched_regime_df
        out2 = enrich_with_regime(out1.copy())
        for col in ["hmm_prob_bull", "hmm_prob_bear", "hmm_prob_chop", "hmm_confidence"]:
            pd.testing.assert_series_equal(out1[col], out2[col], check_names=False)

    def test_handles_empty_dataframe(self):
        from core.chronos import enrich_with_regime
        df = pd.DataFrame(columns=["time", "close"])
        out = enrich_with_regime(df)
        assert "hmm_regime_label" in out.columns
        assert len(out) == 0

    def test_handles_missing_close_column(self):
        from core.chronos import enrich_with_regime
        df = pd.DataFrame({"time": pd.date_range("2024-01-01", periods=10, freq="15min")})
        out = enrich_with_regime(df)
        # Should not crash; should add columns as NaN
        assert "hmm_regime_label" in out.columns
        assert out["hmm_regime_label"].isna().all()

    def test_handles_short_series_gracefully(self):
        """Series shorter than the HMM warmup should return NaN labels
        without crashing."""
        from core.chronos import enrich_with_regime
        df = self._make_df(20)
        out = enrich_with_regime(df)
        assert "hmm_regime_label" in out.columns
        assert len(out) == 20


# ══════════════════════════════════════════════════════════════
#  regime_analysis — performance grouped by regime
# ══════════════════════════════════════════════════════════════
class TestRegimeAnalysis:
    def _trade(self, regime, r_mult):
        return {
            "symbol": "BTCUSDT",
            "direction": "long",
            "r_multiple": r_mult,
            "hmm_regime": regime,
            "hmm_confidence": 0.7,
        }

    def test_returns_dict_keyed_by_regime(self):
        from analysis.stats import regime_analysis
        trades = [
            self._trade("BULL", 1.5),
            self._trade("BULL", -0.5),
            self._trade("BEAR", -1.0),
            self._trade("CHOP", 0.2),
        ]
        result = regime_analysis(trades)
        assert isinstance(result, dict)
        assert set(result.keys()) >= {"BULL", "BEAR", "CHOP"}

    def test_counts_trades_per_regime(self):
        from analysis.stats import regime_analysis
        trades = [self._trade("BULL", 1.0) for _ in range(5)]
        trades += [self._trade("BEAR", -1.0) for _ in range(3)]
        result = regime_analysis(trades)
        assert result["BULL"]["n"] == 5
        assert result["BEAR"]["n"] == 3
        assert result["CHOP"]["n"] == 0

    def test_computes_win_rate(self):
        from analysis.stats import regime_analysis
        trades = [
            self._trade("BULL", 1.0),
            self._trade("BULL", 1.0),
            self._trade("BULL", -1.0),
            self._trade("BULL", -1.0),
        ]
        result = regime_analysis(trades)
        assert result["BULL"]["wr"] == pytest.approx(50.0)

    def test_computes_avg_r_multiple(self):
        from analysis.stats import regime_analysis
        trades = [
            self._trade("BULL", 2.0),
            self._trade("BULL", 1.0),
            self._trade("BULL", -1.0),
        ]
        result = regime_analysis(trades)
        # avg r = (2 + 1 - 1) / 3
        assert result["BULL"]["avg_r"] == pytest.approx(2/3, abs=1e-6)

    def test_handles_empty_trade_list(self):
        from analysis.stats import regime_analysis
        result = regime_analysis([])
        assert result["BULL"]["n"] == 0
        assert result["BEAR"]["n"] == 0
        assert result["CHOP"]["n"] == 0

    def test_ignores_trades_without_regime(self):
        from analysis.stats import regime_analysis
        trades = [
            {"symbol": "BTC", "r_multiple": 1.0},  # no hmm_regime
            self._trade("BULL", 1.0),
        ]
        result = regime_analysis(trades)
        assert result["BULL"]["n"] == 1

    def test_sortino_uses_downside_deviation_not_std(self):
        """Sortino ratio must use sqrt(mean(min(0, r)^2)) — the
        downside deviation — not std of negatives. With wins of
        +2R and losses of -1R, the ratio must be strictly positive."""
        from analysis.stats import regime_analysis
        import pytest
        trades = [
            self._trade("BULL", 2.0),
            self._trade("BULL", 2.0),
            self._trade("BULL", 2.0),
            self._trade("BULL", -1.0),
        ]
        result = regime_analysis(trades)
        # avg_r = (2 + 2 + 2 - 1) / 4 = 1.25
        # downside deviation: only one loss = -1.0 -> sqrt((1^2)/4) = 0.5
        # sortino = 1.25 / 0.5 = 2.5
        assert result["BULL"]["sortino"] == pytest.approx(2.5, abs=1e-4)

    def test_sortino_zero_when_no_losses(self):
        from analysis.stats import regime_analysis
        trades = [self._trade("BULL", 1.0) for _ in range(5)]
        result = regime_analysis(trades)
        assert result["BULL"]["sortino"] == 0.0

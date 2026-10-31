import fit_impact_weights as fit
import numpy as np
import pytest


def _logistic_sample(weights: np.ndarray, n: int = 4000, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, len(weights)))
    y = (rng.random(n) < 1.0 / (1.0 + np.exp(-(x @ weights)))).astype(float)
    return x, y


def test_ridge_logistic_recovers_the_signal_and_shrinks_to_the_prior():
    truth = np.array([1.5, -1.0, 0.0])
    x, y = _logistic_sample(truth)
    free = fit.ridge_logistic(x, y, np.zeros(3), lam=1e-6)
    assert free == pytest.approx(truth, abs=0.15)
    prior = np.array([0.2, 0.2, 0.2])
    assert fit.ridge_logistic(x, y, prior, lam=1e7) == pytest.approx(prior, abs=1e-3)


def test_ridge_logistic_converges_on_separable_data():
    x = np.array([[1.0], [2.0], [-1.0], [-2.0]])
    y = np.array([1.0, 1.0, 0.0, 0.0])
    w = fit.ridge_logistic(x, y, np.zeros(1), lam=0.1)
    assert np.isfinite(w).all() and w[0] > 0


def test_lambda_is_the_smallest_that_keeps_every_v1_sign():
    rng = np.random.default_rng(1)
    prior = np.asarray([fit.PRIOR_WEIGHTS[feature] for _, feature in fit._COLUMNS])
    truth = prior.copy()
    truth[fit._COLUMNS.index(("damage", "Eliminations"))] = -2.0  # the data disagree with v1 on one weight
    x = rng.normal(size=(3000, len(prior)))
    y = (rng.random(3000) < 1.0 / (1.0 + np.exp(-(x @ truth)))).astype(float)
    result = fit.fit_weights(x, y)
    assert result.weights["damage"]["Eliminations"] > 0
    signed = prior != 0.0
    index = fit.LAMBDAS.index(result.lam)
    assert index > 0
    smaller = fit.ridge_logistic(x, y, result.scale * prior, fit.LAMBDAS[index - 1]) / result.scale
    assert np.any(np.sign(smaller[signed]) != np.sign(prior[signed]))


def test_auc_counts_ties_half():
    assert fit.auc(np.array([3.0, 2.0, 1.0]), np.array([1.0, 1.0, 0.0])) == 1.0
    assert fit.auc(np.array([1.0, 1.0]), np.array([1.0, 0.0])) == 0.5
    assert np.isnan(fit.auc(np.array([1.0]), np.array([1.0])))


def test_only_decisive_two_team_maps_are_outcomes():
    rows = [(1, 10, 3.0), (1, 11, 1.0), (2, 20, 0.0), (2, 21, 0.0), (3, 30, 2.0)]
    outcomes = fit.outcomes_from_scores(rows, {1: "t1"})
    assert outcomes.to_dict("records") == [
        {"match_id": 1, "home_team_id": 10, "away_team_id": 11, "home_won": True, "played_at": "t1"}
    ]

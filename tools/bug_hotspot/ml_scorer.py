"""XGBoost "second opinion" — train, evaluate, persist, predict.

This is the optional ML counterpart to the transparent weighted scorer. It is
deliberately built to be honest about its own reliability:

  * Features are language-agnostic process metrics + LOC (percentile-normalized
    per repo) so a model trained on one language transfers to another.
  * Evaluation is **cross-repo** (GroupKFold by repo) so the reported AUC reflects
    generalization to unseen repos, not memorization.
  * It refuses to pretend: too few positive examples -> it declines to train and
    tells you, instead of emitting a confident-looking but meaningless model.

xgboost / scikit-learn / numpy are imported lazily so the rest of GitPulse runs
without them installed.
"""
from __future__ import annotations

import os

from tools.bug_hotspot.normalize import (
    ML_FEATURES,
    feature_matrix,
    percentile_normalize,
)

# modest, regularized defaults — small data, we do not want to overfit
_XGB_PARAMS = dict(
    n_estimators=200,
    max_depth=4,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=2,
    eval_metric="logloss",
    n_jobs=0,
    random_state=0,
)


class NotEnoughData(Exception):
    """Raised when the dataset can't support a meaningful model."""


def _require_libs():
    try:
        import numpy  # noqa: F401
        import xgboost  # noqa: F401
        import sklearn  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "XGBoost second opinion needs extra packages. Install with:\n"
            "    pip install xgboost scikit-learn numpy"
        ) from exc


def _cv_splits(X, y, groups):
    from sklearn.model_selection import GroupKFold, StratifiedKFold

    uniq = len(set(groups))
    if uniq >= 2:
        return list(GroupKFold(n_splits=min(5, uniq)).split(X, y, groups))
    pos = int(sum(y))
    n = min(5, max(2, pos))
    return list(StratifiedKFold(n_splits=n, shuffle=True, random_state=0).split(X, y))


def _precision_at_k(y_true, proba, frac=0.2):
    import numpy as np

    n = len(y_true)
    k = max(1, int(round(frac * n)))
    order = np.argsort(proba)[::-1][:k]
    return float(np.sum(np.asarray(y_true)[order]) / k), k


def train(rows: list[dict], *, min_positives: int = 20):
    """Train an XGBoost model on labeled, snapshot-tagged rows.

    Returns (model, report). Raises NotEnoughData when the data is too thin.
    """
    _require_libs()
    import numpy as np
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import cross_val_predict
    from xgboost import XGBClassifier

    if not rows:
        raise NotEnoughData("no training rows")

    percentile_normalize(rows)  # adds <feat>_pr columns (per-snapshot)
    X = np.asarray(feature_matrix(rows), dtype=float)
    y = np.asarray([int(r["label"]) for r in rows], dtype=int)
    positives = int(y.sum())

    if positives < 3 or positives == len(y):
        raise NotEnoughData(
            f"need both classes with >=3 positives; got {positives} positive / "
            f"{len(y) - positives} negative across {len(y)} rows"
        )

    # prefer cross-repo folds; fall back to per-snapshot if only one repo
    groups = [r.get("repo") for r in rows]
    if len(set(groups)) < 2:
        groups = [r.get("snapshot_id") for r in rows]

    scale_pos_weight = (len(y) - positives) / positives
    model = XGBClassifier(scale_pos_weight=scale_pos_weight, **_XGB_PARAMS)

    # honest, out-of-fold cross-repo estimate
    auc = None
    prec_at_k = None
    k = None
    try:
        splits = _cv_splits(X, y, groups)
        oof = cross_val_predict(model, X, y, cv=splits, method="predict_proba")[:, 1]
        auc = float(roc_auc_score(y, oof))
        prec_at_k, k = _precision_at_k(y, oof)
    except Exception as exc:  # CV can fail on degenerate folds; don't block training
        print(f"  [warn] cross-validation skipped: {type(exc).__name__}: {exc}")

    model.fit(X, y)
    importances = sorted(
        zip(ML_FEATURES, (float(v) for v in model.feature_importances_)),
        key=lambda t: t[1],
        reverse=True,
    )

    report = {
        "n_rows": len(y),
        "positives": positives,
        "negatives": len(y) - positives,
        "repos": len({r.get("repo") for r in rows}),
        "languages": sorted({r.get("language") for r in rows}),
        "auc_cross_repo": auc,
        "precision_at_k": prec_at_k,
        "k": k,
        "scale_pos_weight": round(scale_pos_weight, 3),
        "importances": importances,
        "reliable": positives >= min_positives and (auc is None or auc >= 0.55),
    }
    return model, report


def evaluate_by_language(rows: list[dict]):
    """Leave-one-language-out AUC — demonstrates cross-language transfer.

    Returns {language: auc} for each held-out language (only when >=2 languages
    and the held-out set has both classes).
    """
    _require_libs()
    import numpy as np
    from sklearn.metrics import roc_auc_score
    from xgboost import XGBClassifier

    percentile_normalize(rows)
    langs = sorted({r.get("language") for r in rows})
    if len(langs) < 2:
        return {}

    X = np.asarray(feature_matrix(rows), dtype=float)
    y = np.asarray([int(r["label"]) for r in rows], dtype=int)
    lang_of = np.asarray([r.get("language") for r in rows])

    out = {}
    for held in langs:
        tr = lang_of != held
        te = ~tr
        if y[tr].sum() < 3 or len(set(y[te])) < 2:
            continue
        spw = (len(y[tr]) - y[tr].sum()) / max(1, y[tr].sum())
        m = XGBClassifier(scale_pos_weight=spw, **_XGB_PARAMS)
        m.fit(X[tr], y[tr])
        proba = m.predict_proba(X[te])[:, 1]
        out[held] = float(roc_auc_score(y[te], proba))
    return out


def save_model(model, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    model.save_model(path)


def load_model(path: str):
    if not os.path.isfile(path):
        return None
    try:
        from xgboost import XGBClassifier
    except ImportError:
        return None
    model = XGBClassifier()
    model.load_model(path)
    return model


def predict_scores(model, feature_rows: list[dict]) -> dict[str, float]:
    """Return {path: bug_probability} for live feature rows (one repo, 'now').

    The rows are percentile-normalized as a single snapshot — the same transform
    used at training time — so no scaler needs to be persisted.
    """
    import numpy as np

    rows = [dict(r) for r in feature_rows]
    for r in rows:
        r["_grp"] = "now"
    percentile_normalize(rows, group_key="_grp")
    X = np.asarray(feature_matrix(rows), dtype=float)
    proba = model.predict_proba(X)[:, 1]
    return {r["path"]: float(p) for r, p in zip(rows, proba)}

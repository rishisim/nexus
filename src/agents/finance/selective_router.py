"""Pre-generation routing for selective financial QA.

Only deterministic, pre-answer features are accepted.  The learned route is a
standardized L2 logistic model trained to predict the *benefit* event: ReAct is
correct while static Nexus is wrong.  Model selection follows the frozen ICAIF
protocol, including the conservative rule-gate fallback.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np


RANDOM_SEED = 20260709
N_FOLDS = 5
MIN_BENEFIT_PER_FOLD = 5
MIN_ACCEPTABLE_AUC = 0.60
ACCURACY_SLACK = 0.01

FEATURE_NAMES: Tuple[str, ...] = (
    "question_char_count",
    "question_token_count",
    "evidence_char_count",
    "evidence_token_count",
    "numeric_count",
    "operator_count",
    "period_count",
    "entity_count",
    "has_table",
    "has_conversation",
    "has_narrative",
    "lexical_coverage",
    "retrieval_top_score",
    "retrieval_second_score",
    "retrieval_score_margin",
    "chunk_count",
    "chunk_dispersion",
)

_FORBIDDEN_FEATURE_FRAGMENTS = (
    "answer",
    "correct",
    "derivation",
    "gold",
    "ground_truth",
    "label",
    "reward",
    "scale",
    "target",
)

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does",
    "for", "from", "how", "in", "is", "it", "of", "on", "or", "the", "to",
    "was", "were", "what", "when", "which", "who", "with",
}

_OPERATOR_CUES = re.compile(
    r"\b(?:change|difference|increase|decrease|grew|growth|decline|ratio|percent(?:age)?|"
    r"average|total|sum|combined|more|less|times|divid(?:e|ed)|subtract(?:ed)?|"
    r"multiply|margin|rate|relative to|compared (?:with|to))\b|[+\-*/]",
    re.IGNORECASE,
)
_PERIOD_CUES = re.compile(
    r"\b(?:19|20)\d{2}\b|\bFY\s*\d{2,4}\b|\bQ[1-4]\s*(?:19|20)?\d{0,4}\b|"
    r"\b(?:first|second|third|fourth) quarter\b|\byear[- ]over[- ]year\b",
    re.IGNORECASE,
)
_NARRATIVE_CUES = re.compile(
    r"\b(?:why|explain|implication|impact|strategy|effective|effectiveness|driver|"
    r"indicate|suggest|reflect|reason|risk|outlook|management|business meaning)\b",
    re.IGNORECASE,
)
_CONVERSATION_CUES = re.compile(
    r"\b(?:conversation|previous(?:ly)?|earlier|prior answer|follow[- ]?up|this figure|"
    r"that amount|turn \d+)\b",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*")
_NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\(?\$?\d[\d,]*(?:\.\d+)?%?\)?")
_ENTITY_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z&.-]*(?:\s+[A-Z][A-Za-z&.-]*)+|[A-Z]{2,6})\b"
)


def _tokens(text: str) -> List[str]:
    return [token.lower() for token in _TOKEN_RE.findall(str(text or ""))]


def _content_tokens(text: str) -> set:
    return {token for token in _tokens(text) if token not in _STOPWORDS and len(token) > 1}


def _chunk_score(question_tokens: set, chunk: str) -> float:
    chunk_tokens = _content_tokens(chunk)
    if not question_tokens or not chunk_tokens:
        return 0.0
    return len(question_tokens & chunk_tokens) / len(question_tokens | chunk_tokens)


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def extract_router_features(
    question: str,
    evidence_chunks: Sequence[str] | str,
    *,
    retrieval_scores: Optional[Sequence[float]] = None,
    evidence_stats: Optional[Mapping[str, Any]] = None,
) -> Dict[str, float]:
    """Extract the frozen, pre-answer feature vector.

    ``evidence_stats`` may be supplied by the leakage-safe finance environment.
    It contains retrieval statistics only and takes precedence over locally
    reconstructed scores.  Dataset IDs and target-derived metadata are not
    accepted by this interface.
    """

    if isinstance(evidence_chunks, str):
        chunks = [evidence_chunks]
    else:
        chunks = [str(chunk) for chunk in evidence_chunks]
    evidence = "\n\n".join(chunks)
    question = str(question or "")
    question_tokens = _content_tokens(question)
    evidence_tokens = _content_tokens(evidence)
    local_scores = (
        [_finite(score) for score in retrieval_scores]
        if retrieval_scores is not None
        else [_chunk_score(question_tokens, chunk) for chunk in chunks]
    )
    ranked_scores = sorted(local_scores, reverse=True)
    stats = dict(evidence_stats or {})
    top_score = _finite(stats.get("top_score"), ranked_scores[0] if ranked_scores else 0.0)
    second_score = _finite(
        stats.get("second_score"), ranked_scores[1] if len(ranked_scores) > 1 else 0.0
    )
    score_margin = _finite(stats.get("score_margin"), top_score - second_score)
    if question_tokens:
        local_coverage = len(question_tokens & evidence_tokens) / len(question_tokens)
    else:
        local_coverage = 0.0
    dispersion = float(np.std(local_scores)) if local_scores else 0.0

    # Capitalized noun phrases and ticker-like strings are a deterministic
    # approximation; they require no external NER model or dataset metadata.
    entities = _ENTITY_RE.findall(question)
    features = {
        "question_char_count": float(len(question)),
        "question_token_count": float(len(_tokens(question))),
        "evidence_char_count": float(stats.get("evidence_char_count", len(evidence))),
        "evidence_token_count": float(stats.get("evidence_token_count", len(_tokens(evidence)))),
        "numeric_count": float(len(_NUMBER_RE.findall(question))),
        "operator_count": float(len(_OPERATOR_CUES.findall(question))),
        "period_count": float(len(_PERIOD_CUES.findall(question))),
        "entity_count": float(len(entities)),
        "has_table": float(
            bool(re.search(r"(?:^|\n)\s*(?:table\s*:|[^\n|]+\|[^\n|]+)", evidence, re.I))
        ),
        "has_conversation": float(bool(_CONVERSATION_CUES.search(question + "\n" + evidence))),
        "has_narrative": float(bool(_NARRATIVE_CUES.search(question))),
        "lexical_coverage": _finite(stats.get("lexical_coverage"), local_coverage),
        "retrieval_top_score": top_score,
        "retrieval_second_score": second_score,
        "retrieval_score_margin": score_margin,
        "chunk_count": float(stats.get("evidence_chunk_count", len(chunks))),
        "chunk_dispersion": _finite(stats.get("chunk_dispersion"), dispersion),
    }
    return {name: _finite(features[name]) for name in FEATURE_NAMES}


def validate_feature_mapping(features: Mapping[str, Any]) -> None:
    """Reject missing, unknown, or target-derived model inputs."""

    keys = set(features)
    forbidden = sorted(
        key
        for key in keys
        if any(fragment in str(key).lower() for fragment in _FORBIDDEN_FEATURE_FRAGMENTS)
    )
    if forbidden:
        raise ValueError(f"Target-derived router features are forbidden: {forbidden}")
    missing = sorted(set(FEATURE_NAMES) - keys)
    unknown = sorted(keys - set(FEATURE_NAMES))
    if missing or unknown:
        raise ValueError(f"Invalid router feature schema; missing={missing}, unknown={unknown}")


def feature_vector(features: Mapping[str, Any]) -> np.ndarray:
    validate_feature_mapping(features)
    return np.asarray([_finite(features[name]) for name in FEATURE_NAMES], dtype=float)


@dataclass(frozen=True)
class DevelopmentExample:
    """Development outcome used to train and select a pre-router."""

    features: Mapping[str, float]
    static_correct: bool
    react_correct: bool
    static_cost: float = 1.0
    react_cost: float = 7.0


@dataclass(frozen=True)
class RouterDecision:
    route: str
    benefit_probability: Optional[float]
    mode: str
    threshold: Optional[float]
    reasons: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["reasons"] = list(self.reasons)
        return result


@dataclass
class SelectiveRouter:
    """Serializable frozen router artifact."""

    mode: str
    threshold: Optional[float]
    feature_names: Tuple[str, ...] = FEATURE_NAMES
    means: Optional[List[float]] = None
    scales: Optional[List[float]] = None
    coefficients: Optional[List[float]] = None
    intercept: Optional[float] = None
    coverage_median: Optional[float] = None
    margin_q25: Optional[float] = None
    seed: int = RANDOM_SEED

    def __post_init__(self) -> None:
        if tuple(self.feature_names) != FEATURE_NAMES:
            raise ValueError("Router artifact feature schema does not match the frozen schema")
        if self.mode not in {"learned", "rule"}:
            raise ValueError("Router mode must be 'learned' or 'rule'")
        if self.mode == "rule" and (self.coverage_median is None or self.margin_q25 is None):
            raise ValueError("Rule router requires development coverage and margin thresholds")

    def decide(self, features: Mapping[str, Any]) -> RouterDecision:
        vector = feature_vector(features)
        values = dict(zip(FEATURE_NAMES, vector))
        if self.mode == "learned":
            if any(value is None for value in (self.means, self.scales, self.coefficients, self.intercept, self.threshold)):
                raise ValueError("Incomplete learned router artifact")
            standardized = (vector - np.asarray(self.means)) / np.asarray(self.scales)
            logit = float(np.dot(standardized, np.asarray(self.coefficients)) + float(self.intercept))
            probability = float(_sigmoid(np.asarray([logit]))[0])
            route = "react" if probability >= float(self.threshold) else "nexus"
            return RouterDecision(
                route=route,
                benefit_probability=probability,
                mode=self.mode,
                threshold=float(self.threshold),
                reasons=("benefit_probability_at_or_above_threshold",) if route == "react" else (),
            )

        reasons: List[str] = []
        if values["has_narrative"] >= 0.5:
            reasons.append("narrative_or_implication_question")
        if values["lexical_coverage"] < float(self.coverage_median or 0.0):
            reasons.append("lexical_coverage_below_development_median")
        if values["retrieval_score_margin"] <= float(self.margin_q25 or 0.0):
            reasons.append("retrieval_margin_in_lowest_development_quartile")
        return RouterDecision(
            route="react" if reasons else "nexus",
            benefit_probability=None,
            mode=self.mode,
            threshold=None,
            reasons=tuple(reasons),
        )

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["feature_names"] = list(self.feature_names)
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SelectiveRouter":
        values = dict(payload)
        values["feature_names"] = tuple(values.get("feature_names", FEATURE_NAMES))
        return cls(**values)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "SelectiveRouter":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass(frozen=True)
class RouterTrainingReport:
    router: SelectiveRouter
    fallback_used: bool
    fallback_reason: Optional[str]
    n_examples: int
    benefit_count: int
    cv_auc: Optional[float]
    static_accuracy: float
    react_accuracy: float
    selected_accuracy: float
    selected_mean_cost: float
    selected_escalation_rate: float

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["router"] = self.router.to_dict()
        return result


def _sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-values))


def _fit_standardized_logistic(
    x: np.ndarray,
    y: np.ndarray,
    *,
    l2: float = 1.0,
    max_iter: int = 100,
    tolerance: float = 1e-9,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    means = x.mean(axis=0)
    scales = x.std(axis=0)
    scales[scales < 1e-12] = 1.0
    z = (x - means) / scales
    n_samples, n_features = z.shape
    positives = max(int(y.sum()), 1)
    negatives = max(n_samples - int(y.sum()), 1)
    sample_weights = np.where(y > 0.5, n_samples / (2.0 * positives), n_samples / (2.0 * negatives))
    design = np.column_stack([np.ones(n_samples), z])
    params = np.zeros(n_features + 1, dtype=float)
    regularizer = np.diag(np.r_[0.0, np.full(n_features, l2)])
    weight_sum = float(sample_weights.sum())

    for _ in range(max_iter):
        probabilities = _sigmoid(design @ params)
        gradient = (design.T @ (sample_weights * (probabilities - y))) / weight_sum
        gradient += regularizer @ params / weight_sum
        curvature = sample_weights * probabilities * (1.0 - probabilities)
        hessian = (design.T * curvature) @ design / weight_sum + regularizer / weight_sum
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            step = np.linalg.pinv(hessian) @ gradient
        params -= step
        if float(np.max(np.abs(step))) < tolerance:
            break
    return means, scales, params[1:], float(params[0])


def _stratified_folds(y: np.ndarray, n_folds: int, seed: int) -> List[np.ndarray]:
    rng = np.random.default_rng(seed)
    buckets: List[List[int]] = [[] for _ in range(n_folds)]
    for class_value in (0, 1):
        indices = np.flatnonzero(y == class_value)
        rng.shuffle(indices)
        for offset, index in enumerate(indices):
            buckets[offset % n_folds].append(int(index))
    return [np.asarray(sorted(bucket), dtype=int) for bucket in buckets]


def _auc(y: np.ndarray, scores: np.ndarray) -> Optional[float]:
    positive_count = int(y.sum())
    negative_count = len(y) - positive_count
    if not positive_count or not negative_count:
        return None
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), dtype=float)
    cursor = 0
    while cursor < len(scores):
        end = cursor + 1
        while end < len(scores) and scores[order[end]] == scores[order[cursor]]:
            end += 1
        average_rank = (cursor + 1 + end) / 2.0
        ranks[order[cursor:end]] = average_rank
        cursor = end
    positive_rank_sum = float(ranks[y == 1].sum())
    return (positive_rank_sum - positive_count * (positive_count + 1) / 2.0) / (
        positive_count * negative_count
    )


def _choose_threshold(
    probabilities: np.ndarray,
    static_correct: np.ndarray,
    react_correct: np.ndarray,
    static_cost: np.ndarray,
    react_cost: np.ndarray,
) -> Dict[str, float]:
    target_accuracy = max(float(static_correct.mean()), float(react_correct.mean())) - ACCURACY_SLACK
    maximum = float(probabilities.max()) if len(probabilities) else 0.0
    candidates = [float(np.nextafter(maximum, math.inf))]
    candidates.extend(float(value) for value in sorted(np.unique(probabilities), reverse=True))
    eligible: List[Dict[str, float]] = []
    for threshold in candidates:
        escalate = probabilities >= threshold
        correctness = np.where(escalate, react_correct, static_correct)
        costs = np.where(escalate, react_cost, static_cost)
        row = {
            "threshold": threshold,
            "accuracy": float(correctness.mean()),
            "mean_cost": float(costs.mean()),
            "escalation_rate": float(escalate.mean()),
        }
        if row["accuracy"] + 1e-12 >= target_accuracy:
            eligible.append(row)
    # Routing everything to ReAct always reproduces the ReAct baseline, so the
    # eligible set is nonempty.  The tie break remains explicit and stable.
    return min(
        eligible,
        key=lambda row: (
            row["mean_cost"],
            row["escalation_rate"],
            -row["accuracy"],
            -row["threshold"],
        ),
    )


def _fallback_router(x: np.ndarray) -> SelectiveRouter:
    coverage_idx = FEATURE_NAMES.index("lexical_coverage")
    margin_idx = FEATURE_NAMES.index("retrieval_score_margin")
    return SelectiveRouter(
        mode="rule",
        threshold=None,
        coverage_median=float(np.median(x[:, coverage_idx])),
        margin_q25=float(np.quantile(x[:, margin_idx], 0.25)),
    )


def _evaluate_router(
    router: SelectiveRouter,
    examples: Sequence[DevelopmentExample],
) -> Tuple[float, float, float]:
    routes = np.asarray([router.decide(example.features).route == "react" for example in examples])
    static = np.asarray([bool(example.static_correct) for example in examples])
    react = np.asarray([bool(example.react_correct) for example in examples])
    static_cost = np.asarray([_finite(example.static_cost, 1.0) for example in examples])
    react_cost = np.asarray([_finite(example.react_cost, 7.0) for example in examples])
    accuracy = float(np.where(routes, react, static).mean())
    cost = float(np.where(routes, react_cost, static_cost).mean())
    return accuracy, cost, float(routes.mean())


def train_selective_router(
    examples: Sequence[DevelopmentExample],
    *,
    seed: int = RANDOM_SEED,
    n_folds: int = N_FOLDS,
    l2: float = 1.0,
) -> RouterTrainingReport:
    """Train and freeze the protocol router from development outcomes only."""

    if len(examples) < n_folds:
        raise ValueError(f"At least {n_folds} development examples are required")
    x = np.vstack([feature_vector(example.features) for example in examples])
    static = np.asarray([bool(example.static_correct) for example in examples])
    react = np.asarray([bool(example.react_correct) for example in examples])
    y = (react & ~static).astype(int)
    static_cost = np.asarray([_finite(example.static_cost, 1.0) for example in examples])
    react_cost = np.asarray([_finite(example.react_cost, 7.0) for example in examples])
    folds = _stratified_folds(y, n_folds, seed)
    fold_benefit_counts = [int(y[fold].sum()) for fold in folds]
    fallback_reason: Optional[str] = None
    oof = np.zeros(len(examples), dtype=float)
    cv_auc: Optional[float] = None

    if not y.any() or y.all():
        fallback_reason = "benefit target has only one class"
    elif any(count < MIN_BENEFIT_PER_FOLD for count in fold_benefit_counts):
        fallback_reason = (
            "at least one validation fold has fewer than five usable benefit examples"
        )
    else:
        all_indices = np.arange(len(examples))
        for validation in folds:
            training = np.setdiff1d(all_indices, validation, assume_unique=True)
            means, scales, coefficients, intercept = _fit_standardized_logistic(
                x[training], y[training], l2=l2
            )
            standardized = (x[validation] - means) / scales
            oof[validation] = _sigmoid(standardized @ coefficients + intercept)
        cv_auc = _auc(y, oof)
        if cv_auc is None or cv_auc < MIN_ACCEPTABLE_AUC:
            fallback_reason = f"cross-validated AUROC below {MIN_ACCEPTABLE_AUC:.2f}"

    if fallback_reason:
        router = _fallback_router(x)
        selected_accuracy, selected_cost, escalation_rate = _evaluate_router(router, examples)
    else:
        selection = _choose_threshold(oof, static, react, static_cost, react_cost)
        means, scales, coefficients, intercept = _fit_standardized_logistic(x, y, l2=l2)
        router = SelectiveRouter(
            mode="learned",
            threshold=selection["threshold"],
            means=means.tolist(),
            scales=scales.tolist(),
            coefficients=coefficients.tolist(),
            intercept=intercept,
            seed=seed,
        )
        # Report cross-validated selection performance, not optimistic in-sample
        # performance from the final refit.
        selected_accuracy = selection["accuracy"]
        selected_cost = selection["mean_cost"]
        escalation_rate = selection["escalation_rate"]

    return RouterTrainingReport(
        router=router,
        fallback_used=fallback_reason is not None,
        fallback_reason=fallback_reason,
        n_examples=len(examples),
        benefit_count=int(y.sum()),
        cv_auc=cv_auc,
        static_accuracy=float(static.mean()),
        react_accuracy=float(react.mean()),
        selected_accuracy=selected_accuracy,
        selected_mean_cost=selected_cost,
        selected_escalation_rate=escalation_rate,
    )

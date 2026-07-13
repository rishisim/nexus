"""Leakage-safe, deterministic scoring for the finance benchmark suite.

The objective scorers in this module are intentionally conservative.  They
score one unambiguous final answer, preserve signs, and never award credit for
token overlap or because a gold number appears somewhere in a long response.

FinQA and ConvFinQA originally evaluate executed programs.  Our systems emit
answers rather than programs, so :func:`score_finqa` and
:func:`score_convfinqa` compare the executed answer using the datasets'
five-decimal convention.  TAT-QA follows the official answer/scale
normalization and DROP-style span EM/F1, while inferring the *predicted* scale
only from the prediction.  ``gold_scale`` is scorer-side label data and must
never be passed to a model or router.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import string
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union


Answer = Union[str, int, float, Decimal, Sequence[Union[str, int, float, Decimal]]]

_SCALE_FACTORS = {
    "": Decimal("1"),
    "hundred": Decimal("100"),
    "thousand": Decimal("1000"),
    "million": Decimal("1000000"),
    "billion": Decimal("1000000000"),
    "percent": Decimal("0.01"),
}
_ARTICLES_RE = re.compile(r"\b(?:a|an|the)\b", re.IGNORECASE)
_FINAL_MARKER_RE = re.compile(
    r"(?:final\s+answer|answer)\s*(?:is|=|:)?\s*(.+)$", re.IGNORECASE | re.DOTALL
)
_BOXED_RE = re.compile(r"\\boxed\{([^{}]+)\}")
_FINISH_RE = re.compile(r"^\s*finish\[(.*)]\s*$", re.IGNORECASE | re.DOTALL)
_NUMBER_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[-+]?\$?\s*\d[\d,]*(?:\.\d+)?|\(\s*\$?\s*\d[\d,]*(?:\.\d+)?\s*\))"
    r"(?:\s*(?:%|percent|hundred|thousand|million|billion))?",
    re.IGNORECASE,
)
_FRACTION_RE = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*/\s*([-+]?\d+(?:\.\d+)?)\s*$")


@dataclass(frozen=True)
class ParsedNumber:
    """One unambiguous number normalized to base units."""

    value: Decimal
    scale: str
    raw: str


@dataclass(frozen=True)
class ScoreResult:
    """Serializable per-example objective score."""

    dataset: str
    exact_match: float
    f1: float
    prediction: str
    ground_truth: str
    normalized_prediction: str
    normalized_ground_truth: str
    predicted_scale: str = ""
    gold_scale: str = ""
    answer_type: str = ""
    scoring_method: str = ""
    parse_status: str = "ok"

    @property
    def correct(self) -> bool:
        return self.exact_match == 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _answer_as_string(answer: Answer) -> str:
    if isinstance(answer, (list, tuple)):
        return "; ".join(str(item) for item in answer)
    return "" if answer is None else str(answer)


def extract_final_answer(text: Any) -> str:
    """Extract an explicitly marked answer, otherwise retain the full text.

    Numeric parsing subsequently requires that this segment contain exactly
    one number.  This prevents a derivation such as ``100 - 60 = 40`` from
    receiving credit merely because it happens to mention the gold value.
    """

    value = str(text or "").strip()
    finish_match = _FINISH_RE.match(value)
    if finish_match:
        value = finish_match.group(1).strip()
    boxed = _BOXED_RE.findall(value)
    if boxed:
        return boxed[-1].strip()
    marker = _FINAL_MARKER_RE.search(value)
    if marker:
        return marker.group(1).strip()
    return value


def infer_predicted_scale(prediction: Any) -> str:
    """Infer a TAT-QA scale from the prediction only.

    The function deliberately has no gold-scale parameter, which makes it
    impossible for the scorer to leak a target-derived scale into prediction
    normalization.
    """

    text = extract_final_answer(prediction).lower()
    if "%" in text or re.search(r"\bpercent(?:age)?\b", text):
        return "percent"
    for scale in ("billion", "million", "thousand", "hundred"):
        if re.search(rf"\b{scale}s?\b", text):
            return scale
    return ""


def _decimal_from_token(token: str) -> Optional[ParsedNumber]:
    raw = token.strip()
    scale = infer_predicted_scale(raw)
    negative_parentheses = raw.lstrip().startswith("(") and raw.rstrip().endswith(")")
    cleaned = raw.lower()
    cleaned = re.sub(r"\bpercentage\b|\bpercent\b", "", cleaned)
    cleaned = re.sub(r"\b(?:hundred|thousand|million|billion)s?\b", "", cleaned)
    cleaned = cleaned.replace("%", "").replace("$", "").replace(",", "")
    cleaned = cleaned.strip().strip("()").strip()
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        return None
    if negative_parentheses:
        number = -abs(number)
    return ParsedNumber(number * _SCALE_FACTORS[scale], scale, raw)


def parse_numeric_answer(answer: Any) -> Optional[ParsedNumber]:
    """Parse exactly one numeric final answer into base units.

    Percentages and decimal ratios are thereby comparable (``4.74%`` equals
    ``0.0474``), as are explicit word scales and base-unit answers.  A response
    containing multiple unmarked numbers is rejected as ambiguous.
    """

    text = extract_final_answer(answer)
    fraction = _FRACTION_RE.fullmatch(text)
    if fraction:
        try:
            denominator = Decimal(fraction.group(2))
            if denominator == 0:
                return None
            return ParsedNumber(Decimal(fraction.group(1)) / denominator, "", text)
        except InvalidOperation:
            return None

    matches = [match.group(0) for match in _NUMBER_TOKEN_RE.finditer(text)]
    if len(matches) != 1:
        return None
    return _decimal_from_token(matches[0])


def _round_decimal(value: Decimal, places: int) -> Decimal:
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _numeric_equal(prediction: Any, ground_truth: Any, *, places: int = 5) -> Optional[bool]:
    pred = parse_numeric_answer(prediction)
    gold = parse_numeric_answer(ground_truth)
    if pred is None or gold is None:
        return None
    return _round_decimal(pred.value, places) == _round_decimal(gold.value, places)


def _is_short_numeric_answer(answer: Any) -> bool:
    """Whether a reference is a number plus only innocuous unit/filler words."""

    text = extract_final_answer(answer).lower()
    if len(_NUMBER_TOKEN_RE.findall(text)) != 1:
        return False
    remainder = _NUMBER_TOKEN_RE.sub(" ", text)
    remainder = re.sub(r"[$,.;:()\[\]{}]", " ", remainder)
    words = set(re.findall(r"[a-z]+", remainder))
    allowed = {
        "about",
        "approximately",
        "around",
        "dollar",
        "dollars",
        "usd",
        "us",
    }
    return not (words - allowed)


def _tatqa_gold_value(number: ParsedNumber, gold_scale: str) -> Decimal:
    """Render an annotation the way TAT-QA renders its gold answer."""

    if number.scale:
        # Be defensive if a caller supplies an already scaled gold string.
        return number.value
    return _round_decimal(number.value, 2) * _SCALE_FACTORS[gold_scale]


def _tatqa_prediction_values(number: ParsedNumber) -> Tuple[Decimal, ...]:
    """Return the official-style render plus the no-scale numeric alternative."""

    values = {number.value}
    if number.scale:
        factor = _SCALE_FACTORS[number.scale]
        values.add(_round_decimal(number.value / factor, 2) * factor)
    else:
        # TAT-QA's add_percent_pred keeps an unscaled numeric alternative while
        # get_answer_str also emits its two-decimal rendering.
        values.add(_round_decimal(number.value, 2))
    return tuple(values)


def normalize_span(text: Any) -> str:
    """TAT-QA/DROP-style text normalization without fuzzy containment."""

    value = str(text or "").lower().strip()
    number = parse_numeric_answer(value) if _is_short_numeric_answer(value) else None
    if number is not None:
        normalized_number = format(number.value.normalize(), "f")
        return normalized_number.rstrip("0").rstrip(".") if "." in normalized_number else normalized_number
    value = _ARTICLES_RE.sub(" ", value)
    value = "".join(ch for ch in value if ch not in string.punctuation)
    return " ".join(value.split())


def _span_list(answer: Answer) -> List[str]:
    if isinstance(answer, (list, tuple)):
        return [str(item) for item in answer]
    text = extract_final_answer(answer)
    # Semicolons are an explicit, low-ambiguity separator for multi-span output.
    if ";" in text:
        return [part.strip() for part in text.split(";") if part.strip()]
    return [text]


def _bag_f1(prediction: str, ground_truth: str) -> float:
    pred = set(normalize_span(prediction).split())
    gold = set(normalize_span(ground_truth).split())
    if not pred and not gold:
        return 1.0
    if not pred or not gold:
        return 0.0
    overlap = len(pred & gold)
    if not overlap:
        return 0.0
    precision = overlap / len(pred)
    recall = overlap / len(gold)
    return 2 * precision * recall / (precision + recall)


def _optimal_span_f1(predicted: Sequence[str], gold: Sequence[str]) -> float:
    """Maximum one-to-one span alignment, implemented without SciPy."""

    if not predicted and not gold:
        return 1.0
    if not predicted or not gold:
        return 0.0
    # Dynamic programming over used prediction spans.  TAT-QA multi-span
    # answers are small, so this is both exact and inexpensive.
    dp: Dict[int, float] = {0: 0.0}
    for gold_span in gold:
        next_dp: Dict[int, float] = dict(dp)  # Allow an unmatched gold span.
        for mask, score in dp.items():
            for pred_idx, pred_span in enumerate(predicted):
                bit = 1 << pred_idx
                if mask & bit:
                    continue
                candidate = score + _bag_f1(pred_span, gold_span)
                next_dp[mask | bit] = max(next_dp.get(mask | bit, 0.0), candidate)
        dp = next_dp
    return max(dp.values(), default=0.0) / max(len(predicted), len(gold))


def _span_metrics(prediction: Answer, ground_truth: Answer) -> Tuple[float, float]:
    pred_spans = _span_list(prediction)
    gold_spans = _span_list(ground_truth)
    pred_norm = sorted(normalize_span(span) for span in pred_spans)
    gold_norm = sorted(normalize_span(span) for span in gold_spans)
    exact = float(bool(pred_norm) and pred_norm == gold_norm)
    return exact, round(_optimal_span_f1(pred_spans, gold_spans), 2)


def _binary_text(answer: Any) -> Optional[str]:
    normalized = normalize_span(extract_final_answer(answer))
    if normalized == "yes" or normalized.startswith("yes "):
        return "yes"
    if normalized == "no" or normalized.startswith("no "):
        return "no"
    return None


def _score_execution_answer(dataset: str, prediction: Answer, ground_truth: Answer) -> ScoreResult:
    pred_text = _answer_as_string(prediction)
    gold_text = _answer_as_string(ground_truth)
    numeric = _numeric_equal(prediction, ground_truth, places=5)
    if numeric is not None:
        exact = float(numeric)
        status = "numeric"
    else:
        pred_binary = _binary_text(prediction)
        gold_binary = _binary_text(ground_truth)
        if gold_binary is not None:
            exact = float(pred_binary == gold_binary)
            status = "binary"
        else:
            exact = float(
                bool(normalize_span(prediction))
                and normalize_span(prediction) == normalize_span(ground_truth)
            )
            status = "text"
    return ScoreResult(
        dataset=dataset,
        exact_match=exact,
        f1=exact,
        prediction=pred_text,
        ground_truth=gold_text,
        normalized_prediction=normalize_span(prediction),
        normalized_ground_truth=normalize_span(ground_truth),
        predicted_scale=infer_predicted_scale(prediction),
        scoring_method="executed_answer_5dp",
        parse_status=status,
    )


def score_finqa(prediction: Answer, ground_truth: Answer) -> ScoreResult:
    """Score a FinQA executed answer (program accuracy is out of scope)."""

    return _score_execution_answer("finqa", prediction, ground_truth)


def score_convfinqa(prediction: Answer, ground_truth: Answer) -> ScoreResult:
    """Score a ConvFinQA executed answer with FinQA numeric semantics."""

    return _score_execution_answer("convfinqa", prediction, ground_truth)


def score_tatqa(
    prediction: Answer,
    ground_truth: Answer,
    *,
    gold_scale: str = "",
    answer_type: str = "",
) -> ScoreResult:
    """Score a TAT-QA answer with inferred predicted scale.

    ``gold_scale`` is used only to canonicalize the scorer-side gold answer.
    The predicted scale is always inferred by :func:`infer_predicted_scale`.
    """

    pred_scale = infer_predicted_scale(prediction)
    normalized_gold_scale = str(gold_scale or "").strip().lower()
    if normalized_gold_scale not in _SCALE_FACTORS:
        raise ValueError(f"Unsupported TAT-QA gold scale: {gold_scale!r}")

    kind = str(answer_type or "").strip().lower()
    pred_number = parse_numeric_answer(prediction)
    gold_number = parse_numeric_answer(ground_truth)
    gold_value = (
        _tatqa_gold_value(gold_number, normalized_gold_scale)
        if gold_number is not None
        else None
    )

    numeric_answer_type = kind in {"", "arithmetic", "count"}
    if pred_number is not None and gold_value is not None and numeric_answer_type:
        if kind == "count":
            exact = float(
                pred_number.value == pred_number.value.to_integral_value()
                and gold_value == gold_value.to_integral_value()
                and pred_number.value == gold_value
            )
        else:
            # Official TAT-QA rendering rounds the annotation to two decimal
            # places before formatting the scaled value to four decimals.
            gold_rendered = _round_decimal(gold_value, 4)
            exact = float(
                any(
                    _round_decimal(predicted_value, 4) == gold_rendered
                    for predicted_value in _tatqa_prediction_values(pred_number)
                )
            )
        f1 = exact if kind in {"arithmetic", "count"} or not kind else exact
        status = "numeric"
    else:
        exact, f1 = _span_metrics(prediction, ground_truth)
        status = "span"

    return ScoreResult(
        dataset="tatqa",
        exact_match=exact,
        f1=f1,
        prediction=_answer_as_string(prediction),
        ground_truth=_answer_as_string(ground_truth),
        normalized_prediction=normalize_span(prediction),
        normalized_ground_truth=normalize_span(ground_truth),
        predicted_scale=pred_scale,
        gold_scale=normalized_gold_scale,
        answer_type=kind,
        scoring_method="tatqa_answer_scale_drop",
        parse_status=status,
    )


def score_financebench(prediction: Answer, ground_truth: Answer) -> ScoreResult:
    """Conservative FinanceBench exact/numeric score.

    This is a strict objective sensitivity measure, not a replacement for a
    validated semantic evaluation of narrative answers.
    """

    pred_text = _answer_as_string(prediction)
    gold_text = _answer_as_string(ground_truth)
    numeric = (
        _numeric_equal(prediction, ground_truth, places=5)
        if _is_short_numeric_answer(ground_truth)
        else None
    )
    if numeric is not None:
        exact = float(numeric)
        status = "numeric"
    else:
        pred_binary = _binary_text(prediction)
        gold_binary = _binary_text(ground_truth)
        if gold_binary is not None:
            exact = float(pred_binary == gold_binary)
            status = "binary"
        else:
            exact = float(
                bool(normalize_span(prediction))
                and normalize_span(prediction) == normalize_span(ground_truth)
            )
            status = "strict_text"
    return ScoreResult(
        dataset="financebench",
        exact_match=exact,
        f1=exact,
        prediction=pred_text,
        ground_truth=gold_text,
        normalized_prediction=normalize_span(prediction),
        normalized_ground_truth=normalize_span(ground_truth),
        predicted_scale=infer_predicted_scale(prediction),
        scoring_method="strict_exact_or_numeric_5dp",
        parse_status=status,
    )


def score_dataset(
    dataset: str,
    prediction: Answer,
    ground_truth: Answer,
    **metadata: Any,
) -> ScoreResult:
    """Dispatch to the registered objective scorer for ``dataset``."""

    dataset_id = str(dataset).lower().replace("-", "").replace("_", "")
    if dataset_id == "finqa":
        return score_finqa(prediction, ground_truth)
    if dataset_id == "convfinqa":
        return score_convfinqa(prediction, ground_truth)
    if dataset_id == "tatqa":
        return score_tatqa(
            prediction,
            ground_truth,
            gold_scale=metadata.get("gold_scale", metadata.get("scale", "")),
            answer_type=metadata.get("answer_type", metadata.get("question_type", "")),
        )
    if dataset_id == "financebench":
        return score_financebench(prediction, ground_truth)
    raise ValueError(f"No objective scorer registered for dataset {dataset!r}")


# Semantic stress-test schemas -------------------------------------------------

SEMANTIC_METRICS = ("response_correctness", "faithfulness")


@dataclass(frozen=True)
class SemanticJudgeRequest:
    """Framework-blind request for one semantic judge.

    There is intentionally no framework, route, model-under-test, cost, or
    score field.  Callers retain the blind-ID mapping outside the judge input.
    """

    schema_version: str
    blind_id: str
    question: str
    reference_answer: str
    candidate_answer: str
    evidence: Tuple[str, ...]
    metrics: Tuple[str, ...] = SEMANTIC_METRICS

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("Unsupported semantic judge request schema version")
        if not self.blind_id or not self.question or not self.candidate_answer:
            raise ValueError("blind_id, question, and candidate_answer are required")
        if tuple(self.metrics) != SEMANTIC_METRICS:
            raise ValueError(f"metrics must be exactly {SEMANTIC_METRICS}")

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = list(self.evidence)
        payload["metrics"] = list(self.metrics)
        return payload


@dataclass(frozen=True)
class SemanticJudgeResponse:
    """Validated response emitted by each independent semantic judge."""

    schema_version: str
    blind_id: str
    judge_model: str
    response_correctness: float
    faithfulness: float
    rationale: str
    claims_total: int = 0
    claims_supported: int = 0
    claims_unsupported: int = 0
    status: str = "success"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("Unsupported semantic judge response schema version")
        if not self.blind_id or not self.judge_model:
            raise ValueError("blind_id and judge_model are required")
        if self.status not in {"success", "invalid_response", "judge_error"}:
            raise ValueError("Unsupported semantic judge response status")
        for name in ("response_correctness", "faithfulness"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if min(self.claims_total, self.claims_supported, self.claims_unsupported) < 0:
            raise ValueError("claim counts must be non-negative")
        if self.claims_supported + self.claims_unsupported > self.claims_total:
            raise ValueError("supported + unsupported claims cannot exceed total claims")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SemanticJudgeResponse":
        return cls(
            schema_version=str(payload.get("schema_version", "1.0")),
            blind_id=str(payload["blind_id"]),
            judge_model=str(payload["judge_model"]),
            response_correctness=float(payload["response_correctness"]),
            faithfulness=float(payload["faithfulness"]),
            rationale=str(payload.get("rationale", "")),
            claims_total=int(payload.get("claims_total", 0)),
            claims_supported=int(payload.get("claims_supported", 0)),
            claims_unsupported=int(payload.get("claims_unsupported", 0)),
            status=str(payload.get("status", "success")),
        )


def make_blind_id(example_id: str, candidate_answer: str, *, salt: str) -> str:
    """Return a stable opaque identifier; ``salt`` must not encode framework."""

    if not salt:
        raise ValueError("A non-empty blinding salt is required")
    material = f"{salt}\x00{example_id}\x00{candidate_answer}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:24]


def build_semantic_judge_request(
    *,
    example_id: str,
    question: str,
    reference_answer: str,
    candidate_answer: str,
    evidence: Sequence[str],
    salt: str,
) -> SemanticJudgeRequest:
    return SemanticJudgeRequest(
        schema_version="1.0",
        blind_id=make_blind_id(example_id, candidate_answer, salt=salt),
        question=str(question),
        reference_answer=str(reference_answer),
        candidate_answer=str(candidate_answer),
        evidence=tuple(str(item) for item in evidence),
    )


SEMANTIC_JUDGE_REQUEST_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "FinanceSemanticJudgeRequest",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "blind_id",
        "question",
        "reference_answer",
        "candidate_answer",
        "evidence",
        "metrics",
    ],
    "properties": {
        "schema_version": {"const": "1.0"},
        "blind_id": {"type": "string", "minLength": 8},
        "question": {"type": "string", "minLength": 1},
        "reference_answer": {"type": "string"},
        "candidate_answer": {"type": "string", "minLength": 1},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "metrics": {
            "type": "array",
            "prefixItems": [
                {"const": "response_correctness"},
                {"const": "faithfulness"},
            ],
            "minItems": 2,
            "maxItems": 2,
        },
    },
}

SEMANTIC_JUDGE_RESPONSE_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "FinanceSemanticJudgeResponse",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "blind_id",
        "judge_model",
        "response_correctness",
        "faithfulness",
        "rationale",
        "claims_total",
        "claims_supported",
        "claims_unsupported",
        "status",
    ],
    "properties": {
        "schema_version": {"const": "1.0"},
        "blind_id": {"type": "string"},
        "judge_model": {"type": "string", "minLength": 1},
        "response_correctness": {"type": "number", "minimum": 0, "maximum": 1},
        "faithfulness": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
        "claims_total": {"type": "integer", "minimum": 0},
        "claims_supported": {"type": "integer", "minimum": 0},
        "claims_unsupported": {"type": "integer", "minimum": 0},
        "status": {"enum": ["success", "invalid_response", "judge_error"]},
    },
}


def render_semantic_judge_prompt(request: SemanticJudgeRequest) -> str:
    """Render a deterministic, framework-blind dual-metric judge prompt."""

    rubric = {
        "response_correctness": (
            "Score factual and numerical agreement with the reference answer from 0 to 1. "
            "Do not reward style, verbosity, or unsupported extra claims."
        ),
        "faithfulness": (
            "Score whether every factual claim in the candidate is supported by the supplied "
            "evidence from 0 to 1. Correctness and faithfulness are independent."
        ),
        "output": "Return only JSON conforming to FinanceSemanticJudgeResponse.",
    }
    return (
        "You are a blinded evaluator of financial question answering. The producing system "
        "identity is intentionally unavailable.\n\n"
        f"RUBRIC:\n{json.dumps(rubric, ensure_ascii=False, sort_keys=True)}\n\n"
        f"REQUEST:\n{json.dumps(request.to_dict(), ensure_ascii=False, sort_keys=True)}"
    )


__all__ = [
    "ParsedNumber",
    "ScoreResult",
    "SemanticJudgeRequest",
    "SemanticJudgeResponse",
    "SEMANTIC_JUDGE_REQUEST_SCHEMA",
    "SEMANTIC_JUDGE_RESPONSE_SCHEMA",
    "build_semantic_judge_request",
    "extract_final_answer",
    "infer_predicted_scale",
    "make_blind_id",
    "normalize_span",
    "parse_numeric_answer",
    "render_semantic_judge_prompt",
    "score_convfinqa",
    "score_dataset",
    "score_financebench",
    "score_finqa",
    "score_tatqa",
]

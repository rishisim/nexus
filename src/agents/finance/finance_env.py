"""
Finance environments for Nexus experiments.

The first supported dataset is FinanceBench's public 150-example split. The
environment presents dataset-provided evidence through the same search/lookup/
finish interface used by the existing ReAct and Nexus agents.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _lexical_tokens(text: str) -> set:
    """Return deterministic lexical tokens used by packet search."""
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(text).lower())
        if len(token) > 2
    }


def _rank_evidence_chunks(query: str, chunks: List[str], k: int):
    """Rank chunks and return selected text plus non-gold routing statistics."""
    query_tokens = _lexical_tokens(query)
    query_lower = str(query).lower()
    scored = []
    for idx, chunk in enumerate(chunks):
        chunk_tokens = _lexical_tokens(chunk)
        overlap = len(query_tokens & chunk_tokens)
        substring_bonus = 3 if query_lower and query_lower in chunk.lower() else 0
        scored.append((overlap + substring_bonus, idx, chunk))

    scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    selected = scored[:k]
    selected_chunks = [chunk for _, _, chunk in selected]
    selected_tokens = set()
    for chunk in selected_chunks:
        selected_tokens.update(_lexical_tokens(chunk))

    top_score = selected[0][0] if selected else 0
    second_score = selected[1][0] if len(selected) > 1 else 0
    selected_indices = [idx for _, idx, _ in selected]
    if len(selected_indices) > 1 and len(chunks) > 1:
        dispersion = (max(selected_indices) - min(selected_indices)) / (len(chunks) - 1)
    else:
        dispersion = 0.0

    stats = {
        "evidence_chunk_count": len(chunks),
        "evidence_char_count": sum(len(chunk) for chunk in chunks),
        "evidence_token_count": sum(len(_lexical_tokens(chunk)) for chunk in chunks),
        "selected_chunk_count": len(selected_chunks),
        "selected_char_count": sum(len(chunk) for chunk in selected_chunks),
        "selected_token_count": sum(len(_lexical_tokens(chunk)) for chunk in selected_chunks),
        "query_token_count": len(query_tokens),
        "lexical_coverage": (
            round(len(query_tokens & selected_tokens) / len(query_tokens), 6)
            if query_tokens
            else 0.0
        ),
        "top_score": top_score,
        "second_score": second_score,
        "score_margin": top_score - second_score,
        "selected_indices": selected_indices,
        "chunk_dispersion": round(dispersion, 6),
    }
    return selected_chunks, stats


def _unsearched_evidence_stats(chunks: List[str]) -> Dict:
    """Describe an evidence packet before a query has been issued."""
    return {
        "evidence_chunk_count": len(chunks),
        "evidence_char_count": sum(len(chunk) for chunk in chunks),
        "evidence_token_count": sum(len(_lexical_tokens(chunk)) for chunk in chunks),
        "selected_chunk_count": 0,
        "selected_char_count": 0,
        "selected_token_count": 0,
        "query_token_count": 0,
        "lexical_coverage": 0.0,
        "top_score": 0,
        "second_score": 0,
        "score_margin": 0,
        "selected_indices": [],
        "chunk_dispersion": 0.0,
    }


def _copy_evidence_stats(stats: Dict) -> Dict:
    """Return a defensive copy suitable for result serialization."""
    copied = dict(stats or {})
    copied["selected_indices"] = list(copied.get("selected_indices", []))
    return copied


def normalize_answer(answer: str) -> str:
    """Normalize a short financial answer for deterministic comparison."""
    answer = str(answer or "").lower().strip()
    answer = answer.replace("$", "").replace(",", "")
    answer = answer.replace("u.s.", "us")
    answer = re.sub(r"\busd\b|\bmillions?\b|\bmillion\b", "", answer)
    answer = re.sub(r"[^a-z0-9.\-()% ]+", " ", answer)
    answer = re.sub(r"\s+", " ", answer)
    return answer.strip(" .")


def extract_numbers(answer: str) -> List[float]:
    """Extract numeric values from an answer string."""
    text = str(answer or "").replace(",", "")
    numbers = []
    for match in re.finditer(r"-?\(?\d+(?:\.\d+)?\)?", text):
        value = match.group(0)
        negative = value.startswith("(") and value.endswith(")")
        value = value.strip("()")
        try:
            number = float(value)
        except ValueError:
            continue
        numbers.append(-number if negative else number)
    return numbers


def extract_number(answer: str) -> Optional[float]:
    """Extract the first numeric value from an answer string."""
    numbers = extract_numbers(answer)
    return numbers[0] if numbers else None


def exact_or_numeric_match(prediction: str, ground_truth: str) -> float:
    """Return 1.0 when answers match exactly or numerically within tolerance."""
    pred_norm = normalize_answer(prediction)
    gt_norm = normalize_answer(ground_truth)
    if pred_norm and gt_norm and pred_norm == gt_norm:
        return 1.0

    pred_numbers = extract_numbers(prediction)
    gt_numbers = extract_numbers(ground_truth)
    for pred_num in pred_numbers:
        for gt_num in gt_numbers:
            tolerance = numeric_tolerance(gt_num)
            if abs(pred_num - gt_num) <= tolerance:
                return 1.0
            # Finance statements often show cash outflows in parentheses while
            # the benchmark asks for the absolute expenditure amount.
            if abs(gt_num) > 1 and abs(abs(pred_num) - abs(gt_num)) <= tolerance:
                return 1.0
            # Some finance QA mirrors store ratios as decimals while models
            # naturally answer percentages, e.g. 4.74% vs 0.04741.
            percent_tolerance = numeric_tolerance(gt_num, ratio=True)
            if "%" in str(prediction) and abs((pred_num / 100.0) - gt_num) <= percent_tolerance:
                return 1.0
            if "%" in str(ground_truth) and abs(pred_num - (gt_num / 100.0)) <= percent_tolerance:
                return 1.0

    if pred_norm and gt_norm and (pred_norm in gt_norm or gt_norm in pred_norm):
        return 1.0

    pred_content = content_tokens(prediction)
    gt_content = content_tokens(ground_truth)
    if len(pred_content) >= 2 and pred_content.issubset(gt_content):
        return 1.0
    if len(gt_content) >= 2 and gt_content.issubset(pred_content):
        return 1.0

    overlap = pred_content & gt_content
    if overlap:
        precision = len(overlap) / len(pred_content) if pred_content else 0.0
        recall = len(overlap) / len(gt_content) if gt_content else 0.0
        if precision >= 0.55 and recall >= 0.45:
            return 1.0
        if recall >= 0.75 and precision >= 0.30:
            return 1.0
        if precision >= 0.75 and recall >= 0.30:
            return 1.0

    if yes_no_match(prediction, ground_truth):
        return 1.0
    return 0.0


def numeric_tolerance(ground_truth_number: float, ratio: bool = False) -> float:
    """Tolerance that is not too loose for ratio answers near zero."""
    magnitude = abs(ground_truth_number)
    if ratio or magnitude <= 1:
        return max(0.0005, magnitude * 0.01)
    return max(0.05, magnitude * 0.01)


def yes_no_match(prediction: str, ground_truth: str) -> bool:
    """Handle concise yes/no finance answers with explanatory detail."""
    pred_norm = normalize_answer(prediction)
    gt_norm = normalize_answer(ground_truth)
    pred_yes = pred_norm.startswith("yes")
    gt_yes = gt_norm.startswith("yes")
    pred_no = pred_norm.startswith("no") or pred_norm.startswith("none")
    gt_no = gt_norm.startswith("no") or gt_norm in {"none", "there are none"}
    if (pred_yes and gt_yes) or (pred_no and gt_no):
        pred_tokens = content_tokens(prediction) - {"yes", "no", "none"}
        gt_tokens = content_tokens(ground_truth) - {"yes", "no", "none"}
        if not gt_tokens or len(pred_tokens & gt_tokens) >= 1:
            return True
    return False


def content_tokens(answer: str) -> set:
    """Content-bearing tokens for concise-answer containment checks."""
    stopwords = {
        "a", "an", "and", "are", "as", "at", "by", "for", "from", "in",
        "is", "of", "on", "or", "the", "to", "with", "who", "what", "which",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalize_answer(answer))
        if token not in stopwords and len(token) > 1
    }


def token_f1(prediction: str, ground_truth: str) -> float:
    """Simple token-overlap F1 for short financial answers."""
    pred_tokens = list(content_tokens(prediction))
    gt_tokens = list(content_tokens(ground_truth))
    if not pred_tokens or not gt_tokens:
        return 0.0
    common = set(pred_tokens) & set(gt_tokens)
    if not common:
        return 0.0
    precision = len(common) / len(pred_tokens)
    recall = len(common) / len(gt_tokens)
    return 2 * precision * recall / (precision + recall)


class FinanceBenchEnv:
    """FinanceBench environment backed by the public Hugging Face split."""

    def __init__(self, split: str = "train", data_path: str = None):
        self.split = split
        self.data_path = Path(data_path) if data_path else None
        self.rows = self._load_rows()
        self.current_idx = None
        self.current_row = None
        self.current_passages: List[str] = []
        self.lookup_keyword = None
        self.lookup_results: List[str] = []
        self.lookup_count = 0
        self.answer = None
        self.obs = None
        self.steps = 0
        self.evidence_stats: Dict = _unsearched_evidence_stats([])

    def _load_rows(self) -> List[Dict]:
        if self.data_path:
            with open(self.data_path, "r", encoding="utf-8") as f:
                rows = json.load(f)
            return [self._sanitize_row(dict(row)) for row in rows]

        try:
            from datasets import load_dataset
        except ImportError as exc:
            raise ImportError(
                "FinanceBenchEnv requires the `datasets` package. "
                "Use `nexus_env/bin/python` or install project dependencies."
            ) from exc

        dataset = load_dataset("PatronusAI/financebench", split=self.split)
        return [self._sanitize_row(dict(row)) for row in dataset]

    @staticmethod
    def _sanitize_row(row: Dict) -> Dict:
        """Drop dataset-provided rationales that are not source evidence."""
        row.pop("justification", None)
        return row

    def __len__(self) -> int:
        return len(self.rows)

    def reset(self, idx: int = None) -> str:
        if idx is None:
            idx = 0
        self.current_idx = idx
        self.current_row = self.rows[idx]
        self.current_passages = []
        self.lookup_keyword = None
        self.lookup_results = []
        self.lookup_count = 0
        self.answer = None
        self.steps = 0
        self.obs = self.current_row["question"]
        self.evidence_stats = _unsearched_evidence_stats(self._evidence_chunks())
        return self.obs

    def _metadata_text(self) -> str:
        row = self.current_row
        return (
            f"Company: {row.get('company', '')}\n"
            f"Document: {row.get('doc_name', '')}\n"
            f"Document type: {row.get('doc_type', '')}\n"
            f"Period: {row.get('doc_period', '')}\n"
        )

    def _evidence_chunks(self) -> List[str]:
        row = self.current_row
        chunks = [self._metadata_text()]
        evidence = row.get("evidence") or []
        if isinstance(evidence, dict):
            evidence = [evidence]
        for i, item in enumerate(evidence, 1):
            if isinstance(item, dict):
                text = item.get("evidence_text") or item.get("text") or item.get("content")
                if not text:
                    continue
                source_parts = []
                if item.get("doc_name"):
                    source_parts.append(f"document: {item['doc_name']}")
                if item.get("evidence_page_num") not in (None, ""):
                    source_parts.append(f"page: {item['evidence_page_num']}")
                source = f" ({', '.join(source_parts)})" if source_parts else ""
            else:
                text = str(item)
                source = ""
            chunks.append(f"Evidence {i}{source}:\n{text}")
        return chunks

    @staticmethod
    def _tokenize(text: str) -> set:
        return _lexical_tokens(text)

    @staticmethod
    def _trim(text: str, limit: int = 1800) -> str:
        text = re.sub(r"\n{3,}", "\n\n", str(text)).strip()
        return text if len(text) <= limit else text[:limit].rstrip() + " ..."

    def _search(self, query: str, k: int = 3) -> str:
        chunks = self._evidence_chunks()
        top_chunks, self.evidence_stats = _rank_evidence_chunks(query, chunks, k)
        self.current_passages = top_chunks
        self.lookup_keyword = None
        self.lookup_results = []
        self.lookup_count = 0

        rendered = [f"Search results for: {query}"]
        for i, chunk in enumerate(top_chunks, 1):
            rendered.append(f"[{i}] {self._trim(chunk)}")
        return "\n\n".join(rendered)

    def get_evidence_stats(self) -> Dict:
        """Return non-gold evidence/search features for selective routing."""
        return _copy_evidence_stats(self.evidence_stats)

    def _lookup(self, keyword: str) -> str:
        if not self.current_passages:
            return "No evidence loaded. Use Search[...] first."

        keyword_norm = keyword.lower().strip()
        if self.lookup_keyword != keyword_norm:
            self.lookup_keyword = keyword_norm
            self.lookup_count = 0
            sentences = []
            for passage in self.current_passages:
                sentences.extend(re.split(r"(?<=[.!?])\s+|\n+", passage))
            self.lookup_results = [
                sentence.strip()
                for sentence in sentences
                if keyword_norm and keyword_norm in sentence.lower()
            ]

        if not self.lookup_results:
            return f"No passages containing '{keyword}' found in current evidence."
        if self.lookup_count >= len(self.lookup_results):
            return "No more results."

        result = self.lookup_results[self.lookup_count]
        self.lookup_count += 1
        return f"(Result {self.lookup_count} / {len(self.lookup_results)}) {self._trim(result, limit=800)}"

    def step(self, action: str) -> Tuple[str, float, bool, Dict]:
        action = str(action or "").strip()
        done = False
        reward = 0.0

        if self.answer is not None:
            return self.obs, reward, True, self._get_info()

        lower = action.lower()
        if lower.startswith("search[") and action.endswith("]"):
            query = action[action.find("[") + 1:-1]
            self.obs = self._search(query)
        elif lower.startswith("lookup[") and action.endswith("]"):
            keyword = action[action.find("[") + 1:-1]
            self.obs = self._lookup(keyword)
        elif lower.startswith("table_lookup[") and action.endswith("]"):
            keyword = action[action.find("[") + 1:-1]
            self.obs = self._lookup(keyword)
        elif lower.startswith("tablelookup[") and action.endswith("]"):
            keyword = action[action.find("[") + 1:-1]
            self.obs = self._lookup(keyword)
        elif lower.startswith("think[") and action.endswith("]"):
            self.obs = "Nice thought."
        elif lower.startswith("finish[") and action.endswith("]"):
            self.answer = action[action.find("[") + 1:-1]
            reward = self._compute_reward()
            done = True
            self.obs = f"Episode finished, reward = {reward}"
        else:
            self.obs = f"Invalid action: {action}"

        self.steps += 1
        return self.obs, reward, done, self._get_info()

    def _compute_reward(self) -> float:
        return exact_or_numeric_match(self.answer, self.current_row.get("answer", ""))

    def _get_info(self) -> Dict:
        row = self.current_row or {}
        answer = self.answer or ""
        info = {
            "question_idx": self.current_idx,
            "question_text": row.get("question", ""),
            "answer": answer,
            "source_id": row.get("financebench_id", ""),
            "financebench_id": row.get("financebench_id", ""),
            "company": row.get("company", ""),
            "doc_name": row.get("doc_name", ""),
            "doc_type": row.get("doc_type", ""),
            "doc_period": row.get("doc_period", ""),
            "doc_link": row.get("doc_link", ""),
            "evidence_stats": self.get_evidence_stats(),
        }
        if self.answer is not None:
            gt_answer = row.get("answer", "")
            info.update(
                {
                    "gt_answer": gt_answer,
                    "em": exact_or_numeric_match(answer, gt_answer),
                    "f1": token_f1(answer, gt_answer),
                    "question_type": row.get("question_type", ""),
                    "question_reasoning": row.get("question_reasoning", ""),
                }
            )
        return info


def _load_hf_rows(dataset_name: str, split: str):
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise ImportError(
            "Finance dataset adapters require the `datasets` package. "
            "Use `nexus_env/bin/python` or install project dependencies."
        ) from exc
    return [dict(row) for row in load_dataset(dataset_name, split=split)]


def _stringify_answer(answer) -> str:
    if isinstance(answer, list):
        return ", ".join(str(item) for item in answer)
    return "" if answer is None else str(answer)


def _render_table(table) -> str:
    if isinstance(table, dict):
        table = table.get("table")
    if not isinstance(table, list):
        return str(table) if isinstance(table, (str, int, float)) else ""
    lines = []
    for row in table:
        if isinstance(row, list):
            lines.append(" | ".join(str(cell) for cell in row))
        else:
            lines.append(str(row))
    return "\n".join(lines)


def _extract_between(text: str, start: str, end: str = None) -> str:
    if start not in text:
        return text
    value = text.split(start, 1)[1]
    if end and end in value:
        value = value.split(end, 1)[0]
    return value.strip()


def _extract_question_from_query(query: str, fallback: str = "") -> str:
    matches = re.findall(r"Question:\s*(.*?)\s*Answer:", query, re.DOTALL | re.IGNORECASE)
    if matches:
        return re.sub(r"\s+", " ", matches[-1]).strip()
    return fallback or query[:500]


def _extract_context_from_query(query: str) -> str:
    if "Context:" in query and "Conversations:" in query:
        context = _extract_between(query, "Context:")
        final_question_match = list(re.finditer(r"\nQuestion:\s*", context, re.IGNORECASE))
        if final_question_match:
            context = context[:final_question_match[-1].start()]
        return context.strip()
    if "Context:" in query and "Question:" in query:
        return _extract_between(query, "Context:", "Question:")
    return query


def _split_long_text(text: str, limit: int = 1800, overlap: int = 250) -> List[str]:
    """Split long filing evidence into searchable overlapping chunks."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    if len(text) <= limit:
        return [text] if text else []

    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + limit)
        if end < len(text):
            boundary = max(text.rfind(". ", start, end), text.rfind("</tr>", start, end))
            if boundary > start + int(limit * 0.55):
                end = boundary + (5 if text[boundary:boundary + 5] == "</tr>" else 1)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


class EvidencePacketEnv:
    """Generic finance QA environment over local question/evidence/answer rows."""

    def __init__(self, dataset_id: str, split: str = None):
        self.dataset_id = dataset_id
        self.split = split
        self.rows = self._load_rows()
        self.current_idx = None
        self.current_row = None
        self.current_passages: List[str] = []
        self.lookup_keyword = None
        self.lookup_results: List[str] = []
        self.lookup_count = 0
        self.answer = None
        self.obs = None
        self.steps = 0
        self.evidence_stats: Dict = _unsearched_evidence_stats([])

    def _load_rows(self) -> List[Dict]:
        if self.dataset_id == "finder":
            rows = _load_hf_rows("Linq-AI-Research/FinDER", self.split or "train")
            return [
                {
                    "question": row["text"],
                    "answer": row["answer"],
                    "evidence": row.get("references") or [],
                    "source_id": row.get("_id", ""),
                    "question_type": row.get("type", ""),
                    "category": row.get("category", ""),
                }
                for row in rows
            ]

        if self.dataset_id == "finqa":
            rows = _load_hf_rows("ChanceFocus/flare-finqa", self.split or "valid")
            return [
                {
                    "question": _extract_question_from_query(row["query"], row.get("text", "")),
                    "answer": row["answer"],
                    "evidence": [_extract_context_from_query(row["query"])],
                    "source_id": row.get("id", ""),
                    "question_type": "numerical_financial_qa",
                }
                for row in rows
            ]

        if self.dataset_id == "tatqa":
            rows = _load_hf_rows("next-tat/TAT-QA", self.split or "validation")
            flat_rows = []
            for row_idx, row in enumerate(rows):
                table_text = _render_table(row.get("table"))
                paragraph_text = "\n".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in (row.get("paragraphs") or [])
                )
                evidence = [f"Table:\n{table_text}", f"Paragraphs:\n{paragraph_text}"]
                for question in row.get("questions") or []:
                    if question.get("answer") is None:
                        continue
                    flat_rows.append(
                        {
                            "question": question.get("question", ""),
                            "answer": _stringify_answer(question.get("answer")),
                            "evidence": evidence,
                            "source_id": question.get("uid", f"{row_idx}-{question.get('order', '')}"),
                            "question_type": question.get("answer_type", ""),
                            "answer_from": question.get("answer_from", ""),
                            "gold_scale": question.get("scale", ""),
                        }
                    )
            return flat_rows

        if self.dataset_id == "convfinqa":
            rows = _load_hf_rows("ChanceFocus/flare-convfinqa", self.split or "valid")
            return [
                {
                    "question": _extract_question_from_query(row["query"], row.get("query", "")),
                    "answer": row["answer"],
                    "evidence": [_extract_context_from_query(row["query"])],
                    "source_id": row.get("id", ""),
                    "question_type": "conversational_financial_qa",
                    "turn": row.get("turn", ""),
                    "dialogue_id": row.get("dialogue_id", ""),
                }
                for row in rows
            ]

        raise ValueError(f"Unsupported generic finance dataset: {self.dataset_id}")

    def __len__(self) -> int:
        return len(self.rows)

    def reset(self, idx: int = None) -> str:
        if idx is None:
            idx = 0
        self.current_idx = idx
        self.current_row = self.rows[idx]
        self.current_passages = []
        self.lookup_keyword = None
        self.lookup_results = []
        self.lookup_count = 0
        self.answer = None
        self.steps = 0
        self.obs = self.current_row["question"]
        self.evidence_stats = _unsearched_evidence_stats(self._evidence_chunks())
        return self.obs

    @staticmethod
    def _tokenize(text: str) -> set:
        return _lexical_tokens(text)

    @staticmethod
    def _trim(text: str, limit: int = 2200) -> str:
        text = re.sub(r"\n{3,}", "\n\n", str(text)).strip()
        return text if len(text) <= limit else text[:limit].rstrip() + " ..."

    def _evidence_chunks(self) -> List[str]:
        row = self.current_row
        chunks = [
            f"Dataset: {self.dataset_id}\n"
            f"Source ID: {row.get('source_id', '')}"
        ]
        evidence = row.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        for i, item in enumerate(evidence, 1):
            if isinstance(item, dict):
                item = item.get("evidence_text") or item.get("text") or item.get("content")
                if not item:
                    continue
            split_items = _split_long_text(item)
            for j, chunk in enumerate(split_items, 1):
                label = f"Evidence {i}" if len(split_items) == 1 else f"Evidence {i}.{j}"
                chunks.append(f"{label}:\n{chunk}")
        return chunks

    def _search(self, query: str, k: int = 4) -> str:
        chunks = self._evidence_chunks()
        top_chunks, self.evidence_stats = _rank_evidence_chunks(query, chunks, k)
        self.current_passages = top_chunks
        self.lookup_keyword = None
        self.lookup_results = []
        self.lookup_count = 0
        rendered = [f"Search results for: {query}"]
        for i, chunk in enumerate(top_chunks, 1):
            rendered.append(f"[{i}] {self._trim(chunk)}")
        return "\n\n".join(rendered)

    def get_evidence_stats(self) -> Dict:
        """Return non-gold evidence/search features for selective routing."""
        return _copy_evidence_stats(self.evidence_stats)

    def _lookup(self, keyword: str) -> str:
        if not self.current_passages:
            return "No evidence loaded. Use Search[...] first."
        keyword_norm = keyword.lower().strip()
        if self.lookup_keyword != keyword_norm:
            self.lookup_keyword = keyword_norm
            self.lookup_count = 0
            parts = []
            for passage in self.current_passages:
                parts.extend(re.split(r"(?<=[.!?])\s+|\n+", passage))
            self.lookup_results = [
                part.strip()
                for part in parts
                if keyword_norm and keyword_norm in part.lower()
            ]
        if not self.lookup_results:
            return f"No passages containing '{keyword}' found in current evidence."
        if self.lookup_count >= len(self.lookup_results):
            return "No more results."
        result = self.lookup_results[self.lookup_count]
        self.lookup_count += 1
        return f"(Result {self.lookup_count} / {len(self.lookup_results)}) {self._trim(result, limit=900)}"

    def step(self, action: str) -> Tuple[str, float, bool, Dict]:
        action = str(action or "").strip()
        done = False
        reward = 0.0
        if self.answer is not None:
            return self.obs, reward, True, self._get_info()
        lower = action.lower()
        if lower.startswith("search[") and action.endswith("]"):
            query = action[action.find("[") + 1:-1]
            self.obs = self._search(query)
        elif lower.startswith("lookup[") and action.endswith("]"):
            keyword = action[action.find("[") + 1:-1]
            self.obs = self._lookup(keyword)
        elif lower.startswith("table_lookup[") and action.endswith("]"):
            keyword = action[action.find("[") + 1:-1]
            self.obs = self._lookup(keyword)
        elif lower.startswith("tablelookup[") and action.endswith("]"):
            keyword = action[action.find("[") + 1:-1]
            self.obs = self._lookup(keyword)
        elif lower.startswith("think[") and action.endswith("]"):
            self.obs = "Nice thought."
        elif lower.startswith("finish[") and action.endswith("]"):
            self.answer = action[action.find("[") + 1:-1]
            reward = self._compute_reward()
            done = True
            self.obs = f"Episode finished, reward = {reward}"
        else:
            self.obs = f"Invalid action: {action}"
        self.steps += 1
        return self.obs, reward, done, self._get_info()

    def _compute_reward(self) -> float:
        return exact_or_numeric_match(self.answer, self.current_row.get("answer", ""))

    def _get_info(self) -> Dict:
        row = self.current_row or {}
        answer = self.answer or ""
        info = {
            "question_idx": self.current_idx,
            "question_text": row.get("question", ""),
            "answer": answer,
            "dataset": self.dataset_id,
            "source_id": row.get("source_id", ""),
            "dialogue_id": row.get("dialogue_id", ""),
            "turn": row.get("turn", ""),
            "evidence_stats": self.get_evidence_stats(),
        }
        if self.answer is not None:
            gt_answer = row.get("answer", "")
            gold_scale = row.get("gold_scale", "")
            info.update(
                {
                    "gt_answer": gt_answer,
                    "em": exact_or_numeric_match(answer, gt_answer),
                    "f1": token_f1(answer, gt_answer),
                    "question_type": row.get("question_type", ""),
                    "answer_from": row.get("answer_from", ""),
                    "category": row.get("category", ""),
                    "gold_scale": gold_scale,
                    # Kept only after Finish for compatibility with legacy results.
                    "scale": gold_scale,
                }
            )
        return info


def make_finance_env(dataset_id: str):
    if dataset_id == "financebench":
        return FinanceBenchEnv()
    return EvidencePacketEnv(dataset_id)

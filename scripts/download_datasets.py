"""
Download CREAK, Bamboogle, PopQA, and HoVer datasets from HuggingFace.
Saves processed JSON files to data/ directory.
"""

import json
import os
import sys

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from datasets import load_dataset

DATA_DIR = os.path.join(project_root, "data")
os.makedirs(DATA_DIR, exist_ok=True)


def download_creak():
    """Download CREAK dev split."""
    out_path = os.path.join(DATA_DIR, "creak_dev.json")
    if os.path.exists(out_path):
        print(f"[SKIP] {out_path} already exists")
        return

    print("[DOWNLOAD] CREAK from amydeng2000/CREAK ...")
    ds = load_dataset("amydeng2000/CREAK", split="validation")
    data = []
    for row in ds:
        data.append({
            "sentence": row["sentence"],
            "label": row["label"],
            "entity": row.get("entity", ""),
            "explanation": row.get("explanation", ""),
            "ex_id": row.get("ex_id", ""),
        })
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[DONE] CREAK: {len(data)} examples -> {out_path}")


def download_bamboogle():
    """Download Bamboogle dataset (single split)."""
    out_path = os.path.join(DATA_DIR, "bamboogle.json")
    if os.path.exists(out_path):
        print(f"[SKIP] {out_path} already exists")
        return

    print("[DOWNLOAD] Bamboogle from chiayewken/bamboogle ...")
    ds = load_dataset("chiayewken/bamboogle", split="test")
    data = []
    for row in ds:
        # Handle different possible field names
        question = row.get("question", row.get("Question", ""))
        answers = row.get("golden_answers", row.get("answer", row.get("Answer", "")))
        if isinstance(answers, str):
            answers = [answers]
        data.append({
            "question": question,
            "golden_answers": answers,
        })
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[DONE] Bamboogle: {len(data)} examples -> {out_path}")


def download_popqa():
    """Download PopQA dataset."""
    out_path = os.path.join(DATA_DIR, "popqa.json")
    if os.path.exists(out_path):
        print(f"[SKIP] {out_path} already exists")
        return

    print("[DOWNLOAD] PopQA from akariasai/PopQA ...")
    ds = load_dataset("akariasai/PopQA", split="test")
    data = []
    for row in ds:
        possible_answers = row.get("possible_answers", "")
        if isinstance(possible_answers, str) and possible_answers:
            # Parse string list format like "['answer1', 'answer2']"
            try:
                import ast
                possible_answers = ast.literal_eval(possible_answers)
            except (ValueError, SyntaxError):
                possible_answers = [possible_answers]
        elif not possible_answers:
            possible_answers = [row.get("obj", "")]

        data.append({
            "question": row.get("question", ""),
            "possible_answers": possible_answers if isinstance(possible_answers, list) else [possible_answers],
            "subj": row.get("subj", ""),
            "prop": row.get("prop", ""),
            "obj": row.get("obj", ""),
            "s_pop": row.get("s_pop", 0),
        })
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[DONE] PopQA: {len(data)} examples -> {out_path}")


def download_hover():
    """Download HoVer dataset, filtered to 2-hop dev examples."""
    out_path = os.path.join(DATA_DIR, "hover_dev.json")
    if os.path.exists(out_path):
        print(f"[SKIP] {out_path} already exists")
        return

    print("[DOWNLOAD] HoVer from hover-nlp/hover ...")
    # Try trust_remote_code first, fall back to direct JSON download
    try:
        ds = load_dataset("hover-nlp/hover", split="validation", trust_remote_code=True)
    except Exception as e:
        print(f"[INFO] HuggingFace load failed ({e}), trying direct download...")
        import urllib.request
        url = "https://raw.githubusercontent.com/hover-nlp/hover/main/data/hover/hover_dev_release_v1.1.json"
        tmp_path = os.path.join(DATA_DIR, "_hover_raw.json")
        urllib.request.urlretrieve(url, tmp_path)
        with open(tmp_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        ds = raw_data
        os.remove(tmp_path)

    data = []
    for row in ds:
        num_hops = row.get("num_hops", 0)
        if num_hops != 2:
            continue
        label = row.get("label", "")
        # Normalize label: 0 -> NOT_SUPPORTED, 1 -> SUPPORTED
        if isinstance(label, int):
            label = "SUPPORTED" if label == 1 else "NOT_SUPPORTED"
        elif isinstance(label, str):
            label = label.upper().replace(" ", "_")
        data.append({
            "claim": row.get("claim", ""),
            "label": label,
            "num_hops": num_hops,
            "uid": row.get("uid", ""),
        })
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[DONE] HoVer 2-hop: {len(data)} examples -> {out_path}")


if __name__ == "__main__":
    download_creak()
    download_bamboogle()
    download_popqa()
    download_hover()
    print("\n[ALL DONE] All datasets downloaded successfully.")

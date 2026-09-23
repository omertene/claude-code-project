"""Unit tests for eval/judge.py's extract_json(). No live claude -p calls or API
keys are involved - these test parsing logic against canned text.

Note: judge.py imports `retrieval` at module level, which loads the bge-large and
cross-encoder models (see test_retrieval.py's note). If test_retrieval.py already
ran in this session, Python's module cache means that cost is paid only once for
the whole test run, not once per test file.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
import judge  # noqa: E402

VERDICT = '{"correctly_cited_sources": true, "correctly_declined": "full_decline", "reasoning": "ok"}'


def test_extract_json_clean_response():
    result = judge.extract_json(VERDICT)
    assert result == {
        "correctly_cited_sources": True,
        "correctly_declined": "full_decline",
        "reasoning": "ok",
    }


def test_extract_json_wrapped_in_markdown_fences():
    text = f"```json\n{VERDICT}\n```"
    assert judge.extract_json(text) == {
        "correctly_cited_sources": True,
        "correctly_declined": "full_decline",
        "reasoning": "ok",
    }


def test_extract_json_with_surrounding_prose():
    text = f"Here is my analysis of the answer:\n\n{VERDICT}\n\nHope that helps!"
    assert judge.extract_json(text) == {
        "correctly_cited_sources": True,
        "correctly_declined": "full_decline",
        "reasoning": "ok",
    }


def test_extract_json_raises_when_no_verdict_present():
    with pytest.raises(ValueError):
        judge.extract_json("I couldn't grade this one, sorry.")

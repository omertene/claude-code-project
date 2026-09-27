"""Unit tests for eval/judge.py's extract_json() and judge_record(). No live
claude -p calls or API keys are involved - subprocess.run is mocked where needed,
and the rest test parsing logic against canned text.

Note: judge.py imports `retrieval` at module level, which loads the bge-large and
cross-encoder models (see test_retrieval.py's note). If test_retrieval.py already
ran in this session, Python's module cache means that cost is paid only once for
the whole test run, not once per test file.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def test_judge_record_raises_for_invalid_correctly_declined_value():
    # extract_json() itself doesn't validate correctly_declined - it only checks
    # that "correctly_cited_sources" is present. The category-specific check
    # against DECLINE_VERDICTS happens in judge_record(), after extract_json()
    # has already parsed the (well-formed) verdict.
    record = {
        "id": "test-1",
        "category": "near_miss",
        "question": "What is the capital of France?",
        "answer": "That's outside the scope of this networking knowledge base.",
        "tool_calls": [],
    }
    verdict_json = (
        '{"faithfulness": null, "completeness": null, '
        '"correctly_cited_sources": false, "correctly_declined": "sort of", '
        '"reasoning": "not sure"}'
    )
    mock_result = MagicMock(returncode=0, stdout=verdict_json, stderr="")

    with patch.object(judge.subprocess, "run", return_value=mock_result):
        with pytest.raises(ValueError):
            judge.judge_record(record)

"""Unit tests for src/retrieval.py's pure logic (_first_sentence, retrieve's error
path). No live claude -p calls or API keys are involved.

Note: importing `retrieval` loads the bge-large and cross-encoder models at module
level (see retrieval.py's module docstring), so the first test in this file to run
pays that ~15-20s local model-load cost. That's local compute against models already
cached on disk, not a network/API call, so it fits "pure logic" testing even though
it's not instant.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import retrieval  # noqa: E402


def test_first_sentence_normal_paragraph():
    chunk_text = (
        "## What is a router?\n\n"
        "A router is a device that connects two or more networks. "
        "It forwards data packets between them."
    )
    assert retrieval._first_sentence(chunk_text) == (
        "A router is a device that connects two or more networks."
    )


def test_first_sentence_bullet_list_opener():
    chunk_text = (
        "## Article Summary:\n\n"
        "- SD-WAN decouples networking hardware from the control plane. "
        "It uses software-defined networking to route traffic.\n"
        "- Implementing SD-WAN improves performance."
    )
    assert retrieval._first_sentence(chunk_text) == (
        "SD-WAN decouples networking hardware from the control plane."
    )


def test_first_sentence_no_punctuation_hard_truncates():
    long_body_no_punctuation = "word " * 60  # 300 chars, no . ! or ?
    chunk_text = f"## Heading\n\n{long_body_no_punctuation}"

    result = retrieval._first_sentence(chunk_text, max_chars=220)

    assert result.endswith("...")
    assert len(result) <= 223  # max_chars + "..."
    # The truncated text (without the "...") must be a genuine prefix of the
    # original line, cut at a word boundary - not a mid-word chop.
    without_ellipsis = result[: -len("...")]
    assert long_body_no_punctuation.strip().startswith(without_ellipsis)


def test_retrieve_unknown_article_id_raises_value_error():
    with pytest.raises(ValueError):
        retrieval.retrieve("this-article-does-not-exist")

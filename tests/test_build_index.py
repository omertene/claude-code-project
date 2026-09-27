"""Unit tests for src/build_index.py's chunk_file() heading-based chunking logic.
No live claude -p calls, API keys, or embedding model loads are involved - these
tests exercise pure text-parsing logic and never reach SentenceTransformer.encode()
(that only happens in main(), not chunk_file()).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import build_index  # noqa: E402


def test_chunk_file_raises_when_no_section_headings(tmp_path):
    # A plain document with no "## " headings at all should fail loudly, not
    # silently produce an empty or malformed chunk list.
    doc = tmp_path / "no-headings.txt"
    doc.write_text(
        "# Some Title\n\n"
        "This is a plain document with no section headings at all, just a "
        "paragraph of body text describing something in networking.\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        build_index.chunk_file(doc)

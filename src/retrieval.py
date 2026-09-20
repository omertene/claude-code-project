"""Retrieval functions over the embedding index built in Phase 2 (data/index.json)."""
import json
import re
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

INDEX_PATH = Path(__file__).resolve().parent.parent / "data" / "index.json"
MODEL_NAME = "all-MiniLM-L6-v2"

# Loaded once at import time so repeated calls don't re-read the index or
# re-load the embedding model.
_index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
_embeddings = np.array([c["embedding"] for c in _index], dtype=np.float32)
_embeddings_norm = _embeddings / np.linalg.norm(_embeddings, axis=1, keepdims=True)
_model = SentenceTransformer(MODEL_NAME)


def search(query, top_k=3):
    """Embed `query` and return the top_k most similar chunks by cosine similarity."""
    query_embedding = _model.encode([query])[0].astype(np.float32)
    query_embedding /= np.linalg.norm(query_embedding)

    scores = _embeddings_norm @ query_embedding
    top_indices = np.argsort(-scores)[:top_k]

    results = []
    for i in top_indices:
        chunk = _index[i]
        results.append(
            {
                "article_title": chunk["article_title"],
                "section_heading": chunk["section_heading"],
                "chunk_text": chunk["chunk_text"],
                "similarity_score": float(scores[i]),
            }
        )
    return results


def retrieve(article_id):
    """Return the full text of one article (all its chunks, in order) by article_id
    (the source filename without .txt, e.g. "what-is-bgp")."""
    source_file = f"{article_id}.txt"
    chunks = sorted(
        (c for c in _index if c["source_file"] == source_file),
        key=lambda c: c["id"],
    )
    if not chunks:
        raise ValueError(f"No article found with id '{article_id}'")

    title = chunks[0]["article_title"]
    body = "\n\n".join(c["chunk_text"] for c in chunks)
    return f"# {title}\n\n{body}\n"


def list_docs():
    """Return one entry per article: article_id, title, and a one-line description
    derived from the article's first section."""
    first_chunk_by_source = {}
    for chunk in _index:
        first_chunk_by_source.setdefault(chunk["source_file"], chunk)

    docs = []
    for source_file, chunk in first_chunk_by_source.items():
        docs.append(
            {
                "article_id": source_file[: -len(".txt")],
                "title": chunk["article_title"],
                "description": _first_sentence(chunk["chunk_text"]),
            }
        )
    return docs


def _first_sentence(chunk_text, max_chars=220):
    """Pull a one-line description out of a chunk: the first sentence of its body
    text (the part after the '## heading' line). Handles both plain paragraphs and
    bullet-list openers (e.g. an "Article Summary:" list), and only hard-truncates
    if no sentence-ending punctuation is found at all."""
    _, _, body = chunk_text.partition("\n\n")
    first_block = body.split("\n\n", 1)[0].strip()
    first_line = first_block.split("\n", 1)[0].strip().lstrip("-*").strip()

    match = re.match(r".+?[.!?](?=\s|$)", first_line)
    if match:
        return match.group(0).strip()
    if len(first_line) <= max_chars:
        return first_line
    return first_line[:max_chars].rsplit(" ", 1)[0] + "..."

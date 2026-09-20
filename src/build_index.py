"""Chunk processed articles by ## section headings and embed each chunk
with sentence-transformers (all-MiniLM-L6-v2), writing data/index.json.
"""
import json
import re
from pathlib import Path

from sentence_transformers import SentenceTransformer

PROCESSED_DIR = Path("corpus/processed")
OUT_PATH = Path("data/index.json")
MODEL_NAME = "all-MiniLM-L6-v2"

SECTION_RE = re.compile(r"^## (.+)$", re.M)


def chunk_file(path: Path):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = lines[0].lstrip("#").strip() if lines and lines[0].startswith("#") else path.stem

    # find each "## heading" line and the text that follows until the next "## " or EOF
    matches = list(SECTION_RE.finditer(text))
    chunks = []
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        chunk_text = f"## {heading}\n\n{body}" if body else f"## {heading}"
        chunks.append(
            {
                "source_file": path.name,
                "article_title": title,
                "section_heading": heading,
                "chunk_text": chunk_text,
            }
        )
    return chunks


def main():
    files = sorted(PROCESSED_DIR.glob("*.txt"))
    all_chunks = []
    for path in files:
        all_chunks.extend(chunk_file(path))

    print(f"Chunked {len(files)} files into {len(all_chunks)} chunks. Loading {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME)

    texts = [c["chunk_text"] for c in all_chunks]
    embeddings = model.encode(texts, show_progress_bar=True)

    for chunk, emb in zip(all_chunks, embeddings):
        chunk["embedding"] = emb.tolist()

    for i, chunk in enumerate(all_chunks):
        chunk["id"] = i

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(all_chunks, indent=2), encoding="utf-8")
    print(f"Wrote {len(all_chunks)} chunks to {OUT_PATH}")


if __name__ == "__main__":
    main()

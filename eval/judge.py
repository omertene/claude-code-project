"""LLM-as-judge grader: scores each record in eval/results/traces.jsonl using a
fresh `claude -p` call, and writes one judged result per question to
eval/results/judged.jsonl.

The judge call is deliberately run from a neutral directory (not this project),
so it doesn't pick up this project's .mcp.json / technical-qa-skill (which would
otherwise try to answer the grading prompt itself, or refuse it as out of scope,
instead of grading).
"""
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from retrieval import retrieve as _retrieve  # noqa: E402
from retrieval import search as _search  # noqa: E402

TRACES_PATH = PROJECT_ROOT / "eval" / "results" / "traces.jsonl"
OUT_PATH = PROJECT_ROOT / "eval" / "results" / "judged.jsonl"

# Run the judge subprocess from outside the project so it doesn't see this
# project's .mcp.json / .claude/skills and try to "help" instead of grading.
JUDGE_CWD = tempfile.gettempdir()

CALL_TIMEOUT_SECONDS = 90

DECLINE_CATEGORIES = {"near_miss", "out_of_scope"}
ACCURACY_CATEGORIES = {"single_doc", "multi_doc"}


def load_traces():
    return [
        json.loads(line)
        for line in TRACES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_retrieved_context(tool_calls):
    """Reconstruct the actual chunk_text the system saw, by re-running the same
    search/retrieve calls (with the same logged arguments) against the same
    deterministic index/model used to build the trace."""
    blocks = []
    seen = set()
    for call in tool_calls:
        tool = call["tool"]
        args = call["arguments"]
        if tool == "search":
            results = _search(args.get("query", ""), top_k=args.get("top_k", 3))
            for r in results:
                key = (r["article_title"], r["section_heading"])
                if key in seen:
                    continue
                seen.add(key)
                blocks.append(
                    f"[from \"{r['article_title']}\" - {r['section_heading']}]\n{r['chunk_text']}"
                )
        elif tool == "retrieve":
            article_id = args.get("article_id", "")
            try:
                text = _retrieve(article_id)
            except ValueError:
                continue
            key = ("__full_article__", article_id)
            if key in seen:
                continue
            seen.add(key)
            blocks.append(f"[full article \"{article_id}\"]\n{text}")
        # list_docs calls contribute no chunk-level grounding text; skipped.
    return "\n\n---\n\n".join(blocks)


def build_prompt(record, retrieved_context):
    category = record["category"]

    if category in ACCURACY_CATEGORIES:
        category_guidance = (
            "This question IS covered by the knowledge base, so the system was expected to "
            "answer it using the retrieved context. Score two SEPARATE things, and do not let "
            "one bleed into the other:\n"
            '- "faithfulness" (integer 1-5): are all claims in the answer actually stated in '
            "the retrieved context, with nothing fabricated or inferred beyond it? 5 = every "
            "claim is directly supported by the retrieved context; 1 = the answer contains "
            "fabricated claims, outside knowledge, or contradicts the retrieved context. Judge "
            "ONLY whether what the answer asserts is supported. Do not lower this score because "
            "the answer is short, cautious, or declines to answer - an answer that makes only "
            "supported claims is fully faithful.\n"
            '- "completeness" (integer 1-5): given what the retrieved context contains, did the '
            "answer make full use of it, including reasonable synthesis across articles where "
            "the context supports it? 5 = it covers the key relevant content and draws the "
            "connections the text supports; 1 = it misses most of the relevant content, or "
            "declines/hedges on a question the retrieved context does answer. Reasonable "
            "synthesis means combining statements that ARE in the retrieved context into a "
            "conclusion they directly support - it does not mean adding outside facts. Judge "
            "ONLY coverage and use of the context. Do not lower this score because of "
            "inaccuracy; that belongs to faithfulness.\n"
            '- "correctly_declined": must be null. This question was answerable, so declining '
            "would itself be a failure - reflect that in a low completeness score, and explain "
            "why in completeness_reasoning."
        )
    else:
        category_guidance = (
            "This question is NOT covered by the knowledge base (near_miss: a plausible-sounding "
            "networking question the corpus doesn't actually cover; or out_of_scope: not a "
            "networking question at all). The system was expected to decline rather than answer.\n"
            '- "faithfulness" and "completeness": both must be null (not applicable - there is '
            "nothing in the corpus to be faithful to or to cover).\n"
            '- "correctly_declined": true if the answer explicitly stated the question is outside '
            "the knowledge base / this project's scope and did NOT answer it from general "
            "knowledge; false if it substantively answered the question (from general knowledge, "
            "or by hallucinating corpus support for it)."
        )

    retrieved_block = retrieved_context if retrieved_context else "(no tool calls were made; no chunks were retrieved)"

    return f"""You are an evaluation judge grading one answer from a Q&A system. The system is
supposed to answer ONLY from a fixed 9-article networking knowledge base (retrieved via
search/retrieve tools), and to explicitly decline questions the knowledge base doesn't
cover or that aren't about networking at all, rather than answering from general knowledge.

Question category: {category}
Question: {record['question']}

Answer given by the system:
\"\"\"
{record['answer']}
\"\"\"

Retrieved context (the actual text the system's search/retrieve tool calls returned):
\"\"\"
{retrieved_block}
\"\"\"

{category_guidance}

For "correctly_cited_sources": true if the answer explicitly names the real source
article(s) that the retrieved context above actually came from (and doesn't fabricate
sources or omit citing sources it clearly used); false otherwise. For a correctly-declined
near_miss/out_of_scope answer with no real sources to cite, "correctly_cited_sources" should
be true if the answer doesn't fabricate a source, and false if it cites an article as if it
answered the question when it didn't.

Respond with ONLY a single JSON object, no markdown code fences, no extra commentary before
or after it, with exactly these fields:
{{
  "faithfulness": <integer 1-5 or null>,
  "completeness": <integer 1-5 or null>,
  "correctly_cited_sources": <true or false>,
  "correctly_declined": <true, false, or null>,
  "faithfulness_reasoning": "<one sentence justifying the faithfulness score ONLY; if it is below 5, name the specific claim that is unsupported. null if faithfulness is null>",
  "completeness_reasoning": "<one sentence justifying the completeness score ONLY; if it is below 5, name what relevant content or synthesis was missed. null if completeness is null>",
  "reasoning": "<one sentence justifying correctly_cited_sources and correctly_declined>"
}}"""


def extract_json(text):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"could not find JSON in judge output: {text[:300]!r}")


def judge_record(record):
    retrieved_context = build_retrieved_context(record.get("tool_calls", []))
    prompt = build_prompt(record, retrieved_context)

    result = subprocess.run(
        ["claude", "-p", prompt],
        cwd=JUDGE_CWD,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=CALL_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude -p exited {result.returncode}: {result.stderr.strip()[:500]}")

    verdict = extract_json(result.stdout)
    return {
        "id": record["id"],
        "category": record["category"],
        "question": record["question"],
        "faithfulness": verdict.get("faithfulness"),
        "completeness": verdict.get("completeness"),
        "correctly_cited_sources": verdict.get("correctly_cited_sources"),
        "correctly_declined": verdict.get("correctly_declined"),
        "faithfulness_reasoning": verdict.get("faithfulness_reasoning"),
        "completeness_reasoning": verdict.get("completeness_reasoning"),
        "reasoning": verdict.get("reasoning"),
    }


def main():
    traces = load_traces()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    run_start = time.monotonic()
    succeeded = 0
    failed = 0

    with OUT_PATH.open("w", encoding="utf-8") as out_f:
        for i, record in enumerate(traces, 1):
            print(f"[{i}/{len(traces)}] {record['id']} ({record['category']})", flush=True)
            t0 = time.monotonic()
            try:
                judged = judge_record(record)
            except (subprocess.TimeoutExpired, RuntimeError, ValueError) as e:
                failed += 1
                print(f"    FAILED ({time.monotonic() - t0:.1f}s): {e}", flush=True)
                judged = {
                    "id": record["id"],
                    "category": record["category"],
                    "question": record["question"],
                    "faithfulness": None,
                    "completeness": None,
                    "correctly_cited_sources": None,
                    "correctly_declined": None,
                    "faithfulness_reasoning": None,
                    "completeness_reasoning": None,
                    "reasoning": None,
                    "error": str(e),
                }
            else:
                succeeded += 1
                print(f"    ok ({time.monotonic() - t0:.1f}s)", flush=True)

            out_f.write(json.dumps(judged) + "\n")
            out_f.flush()

    total_elapsed = time.monotonic() - run_start
    print()
    print("=" * 60)
    print(f"Completed: {succeeded}/{len(traces)} succeeded, {failed} failed")
    print(f"Total time: {total_elapsed:.1f}s ({total_elapsed / 60:.1f} min)")
    print(f"Results written to {OUT_PATH}")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

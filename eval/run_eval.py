"""Evaluation harness: runs every question in eval/questions.json through a fresh,
non-interactive `claude -p` call (so the networking-corpus MCP server and the
technical-qa-skill are active), and records the answer plus the tool-call trace
for that question to eval/results/traces.jsonl.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_PATH = PROJECT_ROOT / "eval" / "questions.json"
TRACE_LOG_PATH = PROJECT_ROOT / "logs" / "tool_calls.jsonl"
OUT_PATH = PROJECT_ROOT / "eval" / "results" / "traces.jsonl"

# Read-only MCP tools this harness allows without an interactive approval prompt.
ALLOWED_TOOLS = (
    "mcp__networking-corpus__search,"
    "mcp__networking-corpus__list_docs,"
    "mcp__networking-corpus__retrieve"
)
CALL_TIMEOUT_SECONDS = 180


def load_questions():
    return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))


def read_tool_calls_since(start_timestamp: str):
    """Return [{"tool":..., "arguments":...}] for log entries with a timestamp
    strictly after start_timestamp. ISO-8601 UTC timestamps with a fixed offset
    sort lexically, so plain string comparison is enough."""
    if not TRACE_LOG_PATH.exists():
        return []
    calls = []
    for line in TRACE_LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        entry = json.loads(line)
        if entry["timestamp"] > start_timestamp:
            calls.append({"tool": entry["tool"], "arguments": entry["arguments"]})
    return calls


def run_question(question_text: str):
    """Run one `claude -p` call for this question. Returns (answer_text, error)."""
    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                question_text,
                "--allowedTools",
                ALLOWED_TOOLS,
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=CALL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None, f"timed out after {CALL_TIMEOUT_SECONDS}s"

    if result.returncode != 0:
        return None, f"claude -p exited {result.returncode}: {result.stderr.strip()[:500]}"

    return result.stdout.strip(), None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ids",
        help="Comma-separated question ids to run (default: all). "
        "Other questions' existing results in traces.jsonl are left untouched.",
    )
    args = parser.parse_args()

    all_questions = load_questions()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if args.ids:
        wanted_ids = {qid.strip() for qid in args.ids.split(",") if qid.strip()}
        unknown = wanted_ids - {q["id"] for q in all_questions}
        if unknown:
            print(f"Unknown question id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1
        questions_to_run = [q for q in all_questions if q["id"] in wanted_ids]
    else:
        questions_to_run = all_questions

    # Preserve existing results for questions we're not re-running.
    existing_results = {}
    if OUT_PATH.exists():
        for line in OUT_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                r = json.loads(line)
                existing_results[r["id"]] = r

    run_start = time.monotonic()
    succeeded = 0
    failed = 0

    for i, q in enumerate(questions_to_run, 1):
        print(f"[{i}/{len(questions_to_run)}] {q['id']} ({q['category']}): {q['question']}", flush=True)

        call_start = datetime.now(timezone.utc).isoformat()
        t0 = time.monotonic()
        answer, error = run_question(q["question"])
        elapsed = time.monotonic() - t0

        tool_calls = read_tool_calls_since(call_start)

        record = {
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "answer": answer if answer is not None else "",
            "tool_calls": tool_calls,
        }
        if error:
            record["error"] = error

        existing_results[q["id"]] = record

        if error:
            failed += 1
            print(f"    FAILED ({elapsed:.1f}s): {error}", flush=True)
        else:
            succeeded += 1
            print(f"    ok ({elapsed:.1f}s, {len(tool_calls)} tool call(s))", flush=True)

    # Write out in the original questions.json order (covering all questions we
    # have results for, even ones not in this particular run).
    with OUT_PATH.open("w", encoding="utf-8") as out_f:
        for q in all_questions:
            if q["id"] in existing_results:
                out_f.write(json.dumps(existing_results[q["id"]]) + "\n")

    total_elapsed = time.monotonic() - run_start
    print()
    print("=" * 60)
    print(f"Completed: {succeeded}/{len(questions_to_run)} succeeded, {failed} failed")
    print(f"Total time: {total_elapsed:.1f}s ({total_elapsed / 60:.1f} min)")
    print(f"Results written to {OUT_PATH}")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

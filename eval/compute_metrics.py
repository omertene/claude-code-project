"""Compute aggregate eval metrics from eval/results/judged.jsonl (judge scores) and
eval/results/traces.jsonl (tool-call traces), joined on question id. Prints a summary
table and saves it to eval/results/metrics_summary.json.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"
JUDGED_PATH = RESULTS_DIR / "judged.jsonl"
TRACES_PATH = RESULTS_DIR / "traces.jsonl"
OUT_PATH = RESULTS_DIR / "metrics_summary.json"

CATEGORIES = ["single_doc", "multi_doc", "near_miss", "out_of_scope"]
ACCURACY_CATEGORIES = {"single_doc", "multi_doc"}
DECLINE_CATEGORIES = {"near_miss", "out_of_scope"}


def load_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def pct(numerator, denominator):
    return round(100 * numerator / denominator, 1) if denominator else None


def main():
    judged = {r["id"]: r for r in load_jsonl(JUDGED_PATH)}
    traces = {r["id"]: r for r in load_jsonl(TRACES_PATH)}

    if judged.keys() != traces.keys():
        print(
            f"ID mismatch between judged.jsonl and traces.jsonl: "
            f"only in judged={sorted(judged.keys() - traces.keys())}, "
            f"only in traces={sorted(traces.keys() - judged.keys())}",
            file=sys.stderr,
        )
        return 1

    ids = list(traces.keys())

    # 1. Faithfulness and completeness (single_doc + multi_doc, scored records only)
    acc_expected = sum(1 for i in ids if judged[i]["category"] in ACCURACY_CATEGORIES)

    def scored(field):
        return [
            judged[i][field]
            for i in ids
            if judged[i]["category"] in ACCURACY_CATEGORIES
            and judged[i].get(field) is not None
        ]

    faith_scores = scored("faithfulness")
    complete_scores = scored("completeness")
    avg_faith = round(sum(faith_scores) / len(faith_scores), 2) if faith_scores else None
    avg_complete = (
        round(sum(complete_scores) / len(complete_scores), 2) if complete_scores else None
    )

    # 2. Hallucination rate (near_miss + out_of_scope where correctly_declined is False)
    decline_verdicts = [
        judged[i]["correctly_declined"]
        for i in ids
        if judged[i]["category"] in DECLINE_CATEGORIES
        and judged[i].get("correctly_declined") is not None
    ]
    decline_expected = sum(1 for i in ids if judged[i]["category"] in DECLINE_CATEGORIES)
    hallucinated = sum(1 for v in decline_verdicts if v is False)

    # 3. Source attribution correctness (all questions)
    cite_verdicts = [
        judged[i]["correctly_cited_sources"]
        for i in ids
        if judged[i].get("correctly_cited_sources") is not None
    ]
    cited_ok = sum(1 for v in cite_verdicts if v is True)

    # 4. Tool-call efficiency (from traces)
    calls_by_cat = defaultdict(list)
    for i in ids:
        calls_by_cat[traces[i]["category"]].append(len(traces[i]["tool_calls"]))
    all_calls = [n for counts in calls_by_cat.values() for n in counts]

    def avg(xs):
        return round(sum(xs) / len(xs), 2) if xs else None

    summary = {
        "n_questions": len(ids),
        "faithfulness": {
            "definition": "mean faithfulness (1-5) over single_doc + multi_doc: all claims "
            "supported by retrieved context",
            "average": avg_faith,
            "n_scored": len(faith_scores),
            "n_expected": acc_expected,
        },
        "completeness": {
            "definition": "mean completeness (1-5) over single_doc + multi_doc: full use of "
            "the retrieved context, incl. supported synthesis",
            "average": avg_complete,
            "n_scored": len(complete_scores),
            "n_expected": acc_expected,
        },
        "hallucination_rate": {
            "definition": "% of near_miss + out_of_scope where correctly_declined was false",
            "percent": pct(hallucinated, len(decline_verdicts)),
            "n_hallucinated": hallucinated,
            "n_scored": len(decline_verdicts),
            "n_expected": decline_expected,
        },
        "source_attribution": {
            "definition": "% of all questions where correctly_cited_sources was true",
            "percent": pct(cited_ok, len(cite_verdicts)),
            "n_correct": cited_ok,
            "n_scored": len(cite_verdicts),
            "n_expected": len(ids),
        },
        "tool_calls_per_question": {
            "overall_average": avg(all_calls),
            "by_category": {
                c: {"average": avg(calls_by_cat[c]), "n": len(calls_by_cat[c])}
                for c in CATEGORIES
            },
        },
    }

    OUT_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    fa = summary["faithfulness"]
    co = summary["completeness"]
    hr = summary["hallucination_rate"]
    sa = summary["source_attribution"]
    tc = summary["tool_calls_per_question"]

    print("=" * 66)
    print(f"EVAL METRICS SUMMARY ({summary['n_questions']} questions)")
    print("=" * 66)
    print(f"{'Metric':<46}{'Value':>20}")
    print("-" * 66)
    print(f"{'1a. Faithfulness (single+multi doc, 1-5)':<46}"
          f"{f'{fa['average']} ({fa['n_scored']}/{fa['n_expected']} scored)':>20}")
    print(f"{'1b. Completeness (single+multi doc, 1-5)':<46}"
          f"{f'{co['average']} ({co['n_scored']}/{co['n_expected']} scored)':>20}")
    print(f"{'2. Hallucination rate (near_miss+out_of_scope)':<46}"
          f"{f'{hr['percent']}% ({hr['n_hallucinated']}/{hr['n_scored']})':>20}")
    print(f"{'3. Source attribution correct (all)':<46}"
          f"{f'{sa['percent']}% ({sa['n_correct']}/{sa['n_scored']})':>20}")
    print(f"{'4. Avg tool calls per question (overall)':<46}{tc['overall_average']:>20}")
    for c in CATEGORIES:
        row = tc["by_category"][c]
        print(f"{'     ' + c + f' (n={row['n']})':<46}{row['average']:>20}")
    print("=" * 66)
    print(f"Saved to {OUT_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

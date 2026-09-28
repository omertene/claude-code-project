# Networking Q&A — a corpus-grounded assistant, with an eval

A Claude Code Skill + MCP server that answers networking questions **only from a fixed set of 9 articles**, and says so explicitly when it can't. Ships with an evaluation harness that measures how faithful the answers actually are, rather than asserting it.

**Result: 0 hallucinations across 21 adversarial questions, in all 3 tested retrieval configurations.** The networking content is incidental — what's being tested is one behavior: does the assistant stay inside its knowledge base instead of falling back on what it already knows?

## What it does

Ask a networking question in Claude Code from this project folder, and it will:

1. Check whether the question is about networking at all — if not, decline without searching.
2. Search the knowledge base via the `search`, `list_docs`, and `retrieve` MCP tools.
3. Answer using only what came back, in a fixed shape: direct answer, supporting detail, sources.
4. If the corpus doesn't cover the question, say so explicitly instead of answering from general knowledge.

## Architecture

```
9 Cloudflare articles ──> chunks (one per ## section) ──> embeddings ──> data/index.json
                                                                              │
                          src/retrieval.py  (search / retrieve / list_docs) ◄─┘
                                   │
                          src/mcp_server.py  (MCP tools, logs every call)
                                   │
   .claude/skills/technical-qa-skill  (the rules Claude follows when answering)
```

| Layer | Details |
|---|---|
| **Corpus** | 9 Cloudflare Learning Center articles (network layer, router, switch, routing, BGP, autonomous systems, SD-WAN, subnets, control plane). Content belongs to Cloudflare; used here for a non-commercial personal project. Raw HTML in `corpus/raw/`, cleaned text in `corpus/processed/`. |
| **Index** | 61 chunks, embedded with `BAAI/bge-large-en-v1.5` (1024-dim), stored in `data/index.json`. Upgraded from `all-MiniLM-L6-v2` (384-dim) — see Evaluation below. |
| **Search** | `search()` takes the top 15 chunks by cosine similarity, reranks that pool with a cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`), and returns the top-k after reranking, not before. |
| **MCP server** | Built with FastMCP. Every tool call is appended to `logs/tool_calls.jsonl` with a timestamp, arguments, and a short summary of what was returned. |
| **Skill** | `.claude/skills/technical-qa-skill/SKILL.md` — a four-way classifier (small talk / unrelated topic / plausible networking question / corpus-metadata question) that decides whether to search at all, and forces strict grounding when it does. |

## Evaluation

30 hand-written questions across four categories:

| Category | Count | Correct behavior |
|---|---|---|
| `single_doc` | 5 | Answer from one article |
| `multi_doc` | 4 | Combine two or more articles |
| `near_miss` | 13 | Sounds like networking but isn't (fully) covered — e.g. DNS, IPv6, VPNs, NAT, OSPF, VLANs. Decline, or if the corpus covers part of it, state only that part and decline the rest |
| `out_of_scope` | 8 | Decline — not networking at all |

Each question runs through a fresh `claude -p` call with the Skill and MCP server live; the tool calls it made are captured from the server's own log. A second, independent `claude -p` call acts as an LLM judge and scores each answer against the text retrieval actually returned.

### What improved

Two retrieval upgrades were tested — `bge-large` embeddings, then cross-encoder reranking on top — each measured against the same 30 questions and judge before being kept. The judge only ever sees the chunks retrieval hands it, so it can't observe a retrieval-quality improvement directly; these are the metrics that actually moved:

| Metric | Before | After | Δ |
|---|---|---|---|
| Expected article in top-3 | 89% | 94% | +5 pts |
| MCP cold-start latency | 53s | 13s | −75% |
| Tool calls per question | 1.87 | 1.27 | −34% |

- **Retrieval accuracy (89% → 94%):** a direct, judge-free comparison (cosine similarity only, same 30 queries) found the expected article in the top 3 for 94% of `bge-large`'s results versus 89% for `all-MiniLM-L6-v2`. Not a uniform win — `bge-large` ranked some near-miss chunks (VLAN, MPLS) worse than MiniLM did — but a clear net gain.
- **MCP cold start (53s → 13s):** adding the cross-encoder pushed sequential model loading past Claude Code's tool-connection patience. Loading both models in parallel (`ThreadPoolExecutor`) fixed it — see MCP Server Cold Starts below.

Everything the judge itself scores held steady across all three configurations, which is the expected shape for upgrades that targeted retrieval, not answer quality: faithfulness (claims supported by retrieved text) ran 4.89 → 4.67 → 4.67, completeness (full use of retrieved text) ran 4.67 → 4.78 → 4.67, sources were named correctly on 29–30 of 30 questions throughout, and the hallucination rate stayed at 0/21 across every configuration — the one number that most needed to not move, didn't. Read the flat scores as "no regression," not "no effect": the effect is in the retrieval-accuracy number above, which the judge structurally cannot see. Full per-configuration files: `eval/results/metrics_summary_minilm_baseline.json`, the bge-large-only numbers (git history, commit `deff63f`), and `eval/results/metrics_summary_reranked.json`.

### How declines are scored

For `near_miss` and `out_of_scope` questions, the judge gives one of three verdicts:

- **`full_decline`** — the corpus has nothing on it, and the answer said so.
- **`partial_grounded`** — the corpus covers part of the question; the answer stated only what it supports and explicitly declined the rest. This is correct behavior, not a hallucination.
- **`hallucinated`** — the answer asserted content the retrieved text does not support. Only this counts toward the hallucination rate.

An earlier version scored declines as a yes/no boolean. It marked partly-covered answers (a DDoS question and a CIDR question, both of which quoted only real corpus text) as failures, while the same pattern passed on other runs — conflating correct behavior with the actual failure mode the project is testing for. The verdict was split into three for that reason.

### MCP server cold starts

The MCP server loads its models once at import time. Adding the cross-encoder made this worse: loading `bge-large` and the cross-encoder sequentially took ~53 seconds, comfortably past how long a non-interactive `claude -p` turn will wait for MCP tools before giving up and answering "still connecting" without ever searching. Since the two model loads are independent, loading them in parallel with `ThreadPoolExecutor` (each spends most of its time in disk I/O and C++/tensor-init code that releases the GIL, so they genuinely overlap) cut startup to ~13–20 seconds — faster than even the single-model sequential load.

That fix is reliable for a single question in isolation, but didn't fully hold at the scale of a 30-question batch run. Two infrastructure failures were caught and are documented rather than silently absorbed into the numbers:

- **`nm7` (OSPF)** hit the connection race on all 3 attempts and returned "still connecting" each time. It's recorded as-is — 0 tool calls, judged `full_decline` — which is a failure that looks like a decline, not a real one.
- **`oos7` (Cloudflare's founding)** hit the same race but worked around it by reading `corpus/processed/*.txt` directly instead of using the MCP tools. The answer is fine, but it didn't take the documented tool path, so it isn't a clean data point either.

This is a property of the **eval harness**, not of normal use: `run_eval.py` cold-starts a fresh MCP server subprocess once per question, paying the ~13–20s startup cost 30 times over. A real, long-lived Claude Code session pays that cost exactly once, at session start.

### Caveats

Read these numbers as indicative, not precise.

- **Small sample.** 9 questions are answerable and 21 should be declined. Zero observed hallucinations in 21 is still statistically consistent with a true rate of up to roughly 14%.
- **Judge variance is real.** On unchanged answers, one completeness score came out as 2, then 3, then 2 across runs, with some verdicts flipping — the 100% source-attribution figure is probably partly noise.
- **The judge is validated only on blatant cases.** It labeled a general-knowledge DNS answer `hallucinated` in 6/6 samples, and caught two sentences of outside DDoS knowledge planted in a grounded answer in 3/3. Subtler leaks are untested.
- **The judge can't see retrieval misses.** It only sees the chunks search returned, so a claim that "the corpus lacks X" passes even if search simply missed the relevant chunk. This happened with `nm8` (VLANs): an earlier run's answer said no passage mentions VLANs, but the switch article's managed-switch section does — search ranked it too low, and the judge scored the decline as correct anyway. `nm13` (TCP handshake) may show the same pattern; not yet confirmed.
- **The reranker can be confused by a bare, short query.** Reranking `"What is DNS?"` alone scores an SD-WAN/SDN chunk at 0.97, ahead of every genuinely relevant chunk (cosine similarity alone never ranked it above 7th). Likely cause: surface-level token confusion between "DNS" and "SDN"/"SD-WAN". No real eval answer is affected — every question in `questions.json` is a full sentence, and the reranker scores cleanly on `nm1`'s actual phrasing. It's a real failure mode of the reranking model that this eval's questions don't happen to trigger.

Full per-question output is in `eval/results/`.

## Lessons from building it

- **A skill only runs if its description matches the situation.** The skill originally said "use for networking questions," so it never loaded for an off-topic question — the model just answered it from general knowledge. Broadening the trigger to "use before answering any question in this project" fixed it.
- **One "accuracy" score was hiding two different failure modes.** A faithful but cautious answer scored 2/5 because it declined to draw a connection the retrieved text actually supported. Splitting the score into faithfulness and completeness separated the two cleanly.
- **The judge needs to run outside the project it's grading.** Run from inside the repo, the judge would load the same Skill and try to answer or decline the grading prompt itself, rather than grading it.
- **`mcp` is pinned to `1.30.0`.** Version 2.x renamed `FastMCP` to `MCPServer`, which would silently break a fresh clone.

## Running it

Requires Python 3.14+ (other versions untested) and the [Claude Code](https://claude.com/claude-code) CLI.

**Setup:**

```bash
pip install -r requirements.txt
python src/build_index.py          # builds data/index.json from corpus/processed/
```

The checked-in `.mcp.json` uses a relative command (`python3 src/mcp_server.py`), so a fresh clone should work as-is — no manual `claude mcp add` needed. Two assumptions to be aware of:

- `python3` must resolve via `PATH` to an environment with `requirements.txt` installed. If yours points elsewhere, either fix `PATH` or re-register explicitly: `claude mcp add --scope project networking-corpus -- <path-to-python> src/mcp_server.py`.
- `claude` must be started from the project root — the relative script path resolves against the directory the subprocess is spawned from.

Start `claude` in the repo folder, approve the server when prompted, and ask a networking question.

**Running the eval** (~15 minutes for the questions, ~3–4 minutes for the judge):

```bash
python eval/run_eval.py            # answers   -> eval/results/traces.jsonl
python eval/judge.py               # scores    -> eval/results/judged.jsonl
python eval/compute_metrics.py     # summary   -> eval/results/metrics_summary.json
```

Re-run specific questions with `python eval/run_eval.py --ids sd1,md3`.

The MCP server takes ~26 seconds to start, close to Claude Code's 30-second connect limit. `MCP_TIMEOUT` is set to 120s for the eval, but a run can still occasionally begin before the corpus tools are ready. If a question that should search shows zero tool calls in `traces.jsonl`, re-run it with `--ids`.

**Running the unit tests** (pure logic only — no live `claude -p` calls or API keys):

```bash
pip install -r requirements-dev.txt
pytest
```

## Project layout

```
corpus/raw, corpus/processed                 source articles
data/index.json                              chunks + embeddings
src/build_index.py                           chunk and embed
src/retrieval.py                             search, retrieve, list_docs
src/mcp_server.py                            MCP server with call logging
.claude/skills/technical-qa-skill/SKILL.md   answering rules
eval/questions.json                          the 30 eval questions
eval/run_eval.py, judge.py, compute_metrics.py
eval/results/                                traces, judged scores, metrics summary
tests/                                       unit tests (pytest)
```
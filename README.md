# Networking Q&A: a corpus-grounded assistant, with an eval

A small project that answers networking questions **only from a fixed set of 9 articles**, and says so when it can't. It is built as an MCP server plus a Claude Code skill, and it comes with an evaluation harness that measures how faithful the answers are.

The point is not the networking content. It is testing one behavior: **does the assistant stay inside its knowledge base instead of falling back on what it already knows?**

## What it does

Ask a networking question in Claude Code from this folder and it will:

1. Check whether the question is about networking at all. If not, it declines without searching.
2. Search the knowledge base (`search`, `list_docs`, `retrieve` tools).
3. Answer using only what came back, in a fixed shape: **direct answer, supporting detail, sources**.
4. If the corpus doesn't cover the question, say it's outside the knowledge base instead of answering from general knowledge.

## How it works

```
9 Cloudflare articles ──> chunks (one per ## section) ──> embeddings ──> data/index.json
                                                                              │
                          src/retrieval.py  (search / retrieve / list_docs) ◄─┘
                                   │
                          src/mcp_server.py  (MCP tools, logs every call)
                                   │
   .claude/skills/technical-qa-skill  (the rules Claude follows when answering)
```

- **Corpus:** 9 Cloudflare Learning Center articles (network layer, router, switch, routing, BGP, autonomous systems, SD-WAN, subnets, control plane). The content belongs to Cloudflare and is used here for a personal project. Raw HTML is in `corpus/raw/`, cleaned text in `corpus/processed/`.
- **Index:** 61 chunks, embedded with `all-MiniLM-L6-v2` (384 dimensions), stored in `data/index.json`. Search is cosine similarity.
- **MCP server:** built with FastMCP. Every tool call is appended to `logs/tool_calls.jsonl` with a timestamp, arguments, and a short summary.

## Evaluation

30 hand-written questions in four categories:

| Category | Count | Correct behavior |
|---|---|---|
| `single_doc` | 5 | Answer from one article |
| `multi_doc` | 4 | Combine two or more articles |
| `near_miss` | 13 | Sounds like networking but isn't (fully) covered, e.g. DNS, IPv6, VPNs, NAT, OSPF, VLANs. Decline, or if the corpus covers part of it, state only that part and decline the rest |
| `out_of_scope` | 8 | Decline: not networking at all |

Each question runs through a fresh `claude -p` call, and the tool calls it made are captured. A second `claude -p` call acts as an LLM judge and scores each answer against the text it actually retrieved.

### Results

| Metric | Result |
|---|---|
| Faithfulness (claims supported by retrieved text, 1-5) | 4.89 |
| Completeness (full use of the retrieved text, 1-5) | 4.67 |
| Hallucination rate on `near_miss` + `out_of_scope` | 0 / 21 |
| of which `full_decline` / `partial_grounded` | 15 / 6 |
| Sources named correctly | 30 / 30 |
| Tool calls per question | 1.87 average (0.38 for `out_of_scope`, 2.75 for `multi_doc`) |

### How declines are scored

For `near_miss` and `out_of_scope` questions the judge gives one of three verdicts:

- **`full_decline`**: the corpus has nothing on it, and the answer said so.
- **`partial_grounded`**: the corpus covers part of the question. The answer stated only what the corpus supports and explicitly declined the rest. This is correct behavior, not a hallucination.
- **`hallucinated`**: the answer asserted content the retrieved text does not support. Only this counts toward the hallucination rate.

An earlier version scored declines as a yes/no. It marked partly-covered answers (a DDoS question and a CIDR question, both of which quoted only real corpus text) as failures, and the same kind of answer passed on another run. That mixed correct behavior with the failure the project is looking for, so the verdict was split in three.

### Caveats

**Read these numbers as indicative, not precise.**

- **Small sample.** 9 questions are answerable and 21 should be declined. Zero hallucinations in 21 still allows a true rate up to roughly 14%.
- **The judge varies between runs.** On unchanged answers, one completeness score has come out as 2, then 3, then 2, and some verdicts have flipped, so the 100% source-attribution figure is probably partly noise.
- **The judge is tested only on blatant cases.** It labeled a general-knowledge DNS answer `hallucinated` in 6 of 6 samples, and caught two sentences of outside DDoS knowledge inserted into a grounded answer in 3 of 3. Subtle leaks are untested.
- **The judge cannot see retrieval misses.** It only sees the chunks search returned, so a wrong claim that the corpus lacks something passes if search missed it. This happened with `nm8` (VLANs): in an earlier run the answer said no passage mentions VLANs, but the switch article's managed-switch section does. Search ranked that chunk low, and the judge scored the decline as correct. `nm13` (TCP handshake) shows the same possible pattern: it was scored `full_decline`, yet the corpus names TCP as a transport-layer protocol. I have not confirmed whether search missed it.

Full per-question output is in `eval/results/`.

## Run it

Developed on Python 3.14 (other versions untested). Requires the [Claude Code](https://claude.com/claude-code) CLI.

```bash
pip install -r requirements.txt
python src/build_index.py          # rebuilds data/index.json from corpus/processed/
```

Register the MCP server for this project. The path to `.mcp.json` in the repo is specific to the original machine, so re-register with your own paths:

```bash
claude mcp add --scope project networking-corpus -- <path-to-python> <path-to-repo>/src/mcp_server.py
```

Then start `claude` in the repo folder, approve the server when prompted, and ask a networking question.

To run the eval (about 15 minutes for the questions, 3-4 for the judge):

```bash
python eval/run_eval.py            # answers -> eval/results/traces.jsonl
python eval/judge.py               # scores  -> eval/results/judged.jsonl
python eval/compute_metrics.py     # summary -> eval/results/metrics_summary.json
```

`run_eval.py --ids sd1,md3` re-runs just those questions.

The MCP server takes about 26 seconds to start, close to Claude Code's 30-second connect limit. The eval sets `MCP_TIMEOUT` to 120 seconds, but a run can still occasionally begin without the corpus tools. If a question that should search shows zero tool calls in `traces.jsonl`, re-run it with `--ids`.

## Project layout

```
corpus/raw, corpus/processed    source articles
data/index.json                 chunks + embeddings
src/build_index.py              chunk and embed
src/retrieval.py                search, retrieve, list_docs
src/mcp_server.py               MCP server with call logging
.claude/skills/technical-qa-skill/SKILL.md   answering rules
eval/questions.json             the 30 questions
eval/run_eval.py, judge.py, compute_metrics.py
eval/results/                   traces, judged scores, metrics summary
```

## Lessons from building it

- **A skill only runs if its description matches the situation.** The skill first said "use for networking questions", so it never loaded for a question about cookies, and the model just answered it. Broadening the description to "use before answering any question in this project" fixed it.
- **One "accuracy" score hid two different things.** A faithful but cautious answer scored 2/5 because it declined to draw a connection the text supported. Splitting the score into faithfulness and completeness separated them.
- **Judges need running from outside the project.** Run inside it, the judge would load the same skill and try to answer or refuse the grading prompt instead of grading it.
- **`mcp` is pinned to 1.30.0.** Version 2.x renamed `FastMCP` to `MCPServer`.

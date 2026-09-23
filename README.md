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
- **Index:** 61 chunks, embedded with `BAAI/bge-large-en-v1.5` (1024 dimensions), stored in `data/index.json`. Upgraded from `all-MiniLM-L6-v2` (384 dimensions) for stronger retrieval quality — see Evaluation → Results below.
- **Search:** `search()` takes the top 15 chunks by cosine similarity, then reranks that pool with a cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) and returns the top_k after reranking, not before. A cross-encoder reads the query and each candidate chunk together in one pass, rather than comparing two separately-computed embeddings, which can catch relevance nuances plain cosine similarity misses.
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

Three retrieval configurations were run through the same 30 questions and the same judge: the original `all-MiniLM-L6-v2` setup, `bge-large` alone, and `bge-large` with the cross-encoder reranking step added on top.

| Metric | MiniLM | bge-large | bge-large + rerank |
|---|---|---|---|
| Faithfulness (claims supported by retrieved text, 1-5) | 4.89 | 4.67 | 4.67 |
| Completeness (full use of the retrieved text, 1-5) | 4.67 | 4.78 | 4.67 |
| Hallucination rate on `near_miss` + `out_of_scope` | 0 / 21 | 0 / 21 | 0 / 21 |
| of which `full_decline` / `partial_grounded` | 15 / 6 | 15 / 6 | 16 / 5 |
| Sources named correctly | 30 / 30 | 29 / 30 | 30 / 30 |
| Tool calls per question, overall | 1.87 | 1.83 | 1.27 |

Full files: `eval/results/metrics_summary_minilm_baseline.json`, the bge-large-only numbers (git history, commit `deff63f`), and `eval/results/metrics_summary_reranked.json`.

**Be honest about what this does and doesn't show.** Faithfulness, completeness, and the hallucination rate are flat across all three configurations, within this eval's noise (the judge alone has moved a score by a point on an unchanged answer — see Caveats). This 30-question eval is not sensitive enough to prove an end-to-end quality difference either way.

That doesn't mean the embedding upgrade did nothing — it measurably improved retrieval itself, just not in a way this eval can see. A direct comparison (cosine similarity only, no LLM, same 30 queries) found: on the 9 answerable questions, both models put the top-1 result on an expected article 8/9 of the time, but the expected article appeared somewhere in the top 3 for 94% of bge-large's results versus 89% for MiniLM. On chunks that only mention a near-miss topic in passing, bge-large ranked the OSPF chunk 4th (MiniLM: 5th) and tied on IPv6 (1st); it ranked VLAN and MPLS *worse* than MiniLM did (8th and 5th vs. 6th and 1st) — not a uniform win. The lower tool-call average for bge-large + rerank in the table above is mostly an artifact of two infrastructure failures during that run, not a retrieval-quality signal — see "MCP server cold starts" below.

### How declines are scored

For `near_miss` and `out_of_scope` questions the judge gives one of three verdicts:

- **`full_decline`**: the corpus has nothing on it, and the answer said so.
- **`partial_grounded`**: the corpus covers part of the question. The answer stated only what the corpus supports and explicitly declined the rest. This is correct behavior, not a hallucination.
- **`hallucinated`**: the answer asserted content the retrieved text does not support. Only this counts toward the hallucination rate.

An earlier version scored declines as a yes/no. It marked partly-covered answers (a DDoS question and a CIDR question, both of which quoted only real corpus text) as failures, and the same kind of answer passed on another run. That mixed correct behavior with the failure the project is looking for, so the verdict was split in three.

### MCP server cold starts, and the eval harness's reliability cost

The MCP server loads its model(s) once at import time (see "Lessons from building it"). Adding the cross-encoder made this worse: loading `bge-large` and the cross-encoder one after another took ~53 seconds — comfortably past how long a single non-interactive `claude -p` turn will keep polling for MCP tools before giving up and answering "still connecting" without ever searching. Diagnosis: the two model loads are independent, so there's no reason to do them sequentially. Loading them in parallel with `ThreadPoolExecutor` (each spends most of its time in disk I/O and C++/tensor-init code that releases Python's GIL, so they genuinely overlap) cut startup to ~13-20s — faster than even the bge-large-only version's sequential single-model load.

That fix works reliably for a single question in isolation. It did not fully solve the problem at the scale of a 30-question batch run: getting one clean pass took several retry rounds, and turned up two infrastructure failures that had been silently miscounted as real results:

- **`nm7` (OSPF) never got a genuine answer.** 3 of 3 attempts hit the connection race and returned "still connecting." It's recorded as-is — 0 tool calls, judged `full_decline` — which is not a real decline, just a failure that happens to look like one.
- **`oos7` (Cloudflare's founding) hit the same race but worked around it**, by reading `corpus/processed/*.txt` directly instead of using the `search`/`retrieve` MCP tools. The resulting answer is fine, but it didn't take the documented tool path, so it's not a clean data point on that path either.

This is a property of the **eval harness**, not of using the system normally: `run_eval.py` cold-starts a brand-new MCP server subprocess once per question, so a long sequential run pays that ~13-20s startup cost 30 times over, and any slow or contended startup among those 30 has a chance to lose the race. A real, single, long-lived Claude Code session pays that cost exactly once, at the start of the session, and never hits this again.

### Caveats

**Read these numbers as indicative, not precise.**

- **Small sample.** 9 questions are answerable and 21 should be declined. Zero hallucinations in 21 still allows a true rate up to roughly 14%.
- **The judge varies between runs.** On unchanged answers, one completeness score has come out as 2, then 3, then 2, and some verdicts have flipped, so the 100% source-attribution figure is probably partly noise.
- **The judge is tested only on blatant cases.** It labeled a general-knowledge DNS answer `hallucinated` in 6 of 6 samples, and caught two sentences of outside DDoS knowledge inserted into a grounded answer in 3 of 3. Subtle leaks are untested.
- **The judge cannot see retrieval misses.** It only sees the chunks search returned, so a wrong claim that the corpus lacks something passes if search missed it. This happened with `nm8` (VLANs): in an earlier run the answer said no passage mentions VLANs, but the switch article's managed-switch section does. Search ranked that chunk low, and the judge scored the decline as correct. `nm13` (TCP handshake) shows the same possible pattern: it was scored `full_decline`, yet the corpus names TCP as a transport-layer protocol. I have not confirmed whether search missed it.
- **The cross-encoder reranker can be confused by a bare, short query.** Reranking `"What is DNS?"` alone scored an SD-WAN/SDN chunk at 0.97 confidence, ahead of every genuinely relevant chunk — cosine similarity alone had never ranked it above 7th place. The likely cause is surface-level token confusion between the acronyms "DNS" and "SDN"/"SD-WAN". This didn't affect any actual eval answer: every real question in `questions.json` is phrased as a full sentence, and re-running the same reranker against `nm1`'s actual wording ("What is DNS and how does it resolve domain names to IP addresses?") gave clean, near-zero scores across the board. It's a real failure mode of the reranking model, just not one this eval's questions happen to trigger.

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

---
name: technical-qa-skill
description: Use before answering ANY question asked in this project, not just ones that already look like networking questions — this skill is what decides whether a question is a networking question in scope for the corpus (routers, switches, routing, BGP, autonomous systems, SD-WAN, subnets, the control plane, the network layer), a plausible-but-uncovered networking question, or unrelated to networking entirely. Enforces answering strictly from the corpus via list_docs/search/retrieve with no outside knowledge, explicit source citation, and an explicit "outside this project's scope" response for anything the corpus doesn't cover or that isn't networking-related at all — consult it first rather than judging relevance on your own.
---

# Technical Q&A over the networking corpus

This project is specifically testing faithfulness to a small, fixed knowledge base
(9 Cloudflare Learning Center articles, exposed via the `networking-corpus` MCP
server's `list_docs`, `search`, and `retrieve` tools). When answering a networking
question in this project, follow this process exactly.

## 1. Screen for relevance before doing anything else

First judge whether the question is even plausibly about networking.

- **Clearly unrelated to networking** (not even plausibly networking-adjacent —
  e.g. cooking, sports, geography, creative writing, math): do not call any tool,
  and do not answer from general knowledge either. State clearly and directly that
  the question is outside this project's scope. Skip straight to this; there is
  nothing to search for.
- **Plausibly networking-related** (it's a networking question, term, or concept —
  even one you suspect isn't covered, like DNS or VPNs): proceed to step 2. Being
  unsure whether the corpus covers it is not the same as being unrelated to
  networking — check first.

## 2. Always check the knowledge base first

For any question that passed step 1, consult the tools — never answer a networking
question from memory alone.

- If you're not sure what the corpus covers, call `list_docs` first to see the
  available articles.
- Call `search` with the user's question (or a close paraphrase) to find the most
  relevant passages.
- Call `retrieve` on a specific article when a single chunk isn't enough context —
  e.g. the question spans multiple sections of one article, or you need the full
  article to be confident in the answer.

## 3. Ground the answer strictly in what the tools returned

Answer using only the text actually returned by `search`/`retrieve`. Do not
supplement, correct, extend, or "fill in" with general knowledge about networking —
even when you know more about the topic than the corpus says, and even when the
corpus is incomplete, simplified, or uses different terminology than you would.
Do not blend outside knowledge into an otherwise corpus-grounded answer.

## 4. If the corpus doesn't clearly answer it, say so

Before answering, check whether the retrieved content actually and directly answers
the question. If it doesn't — the topic isn't covered, or what's covered is only
tangentially related — explicitly tell the user this question is outside this
knowledge base. Do not then go on to answer from general knowledge anyway. A partial
or vague match is not a match: if in doubt, say it's not covered.

## 5. Always cite the source article(s)

Every answer must explicitly name which article(s) it's based on (e.g. by title,
as returned in `article_title`). If multiple articles/chunks contributed, name all
of them. If the question is out of scope per step 1 or step 4, there's no source to
cite — say so instead.

## 6. Structure every answer the same way

1. **Direct answer** — a short, direct answer to the question (or a direct statement
   that it's outside this project's scope, per step 1, or outside this knowledge
   base, per step 4).
2. **Supporting detail** — the relevant explanation/detail pulled from the retrieved
   text (or, for a step-1 decline, a brief note on why the question isn't a
   networking question).
3. **Source(s)** — which article(s) the answer came from.

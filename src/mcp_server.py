"""MCP server exposing the networking-corpus retrieval functions (src/retrieval.py)
as tools, via the official Python MCP SDK's FastMCP.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent))
from retrieval import list_docs as _list_docs  # noqa: E402
from retrieval import retrieve as _retrieve  # noqa: E402
from retrieval import search as _search  # noqa: E402

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "tool_calls.jsonl"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

mcp = FastMCP("networking-corpus")


def _log_call(tool_name: str, arguments: dict, summary: str) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool_name,
        "arguments": arguments,
        "summary": summary,
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


@mcp.tool()
def search(query: str, top_k: int = 3) -> list[dict]:
    """Semantic search over a small corpus of Cloudflare Learning Center articles on
    core networking concepts: the network layer, routers, switches, routing, BGP,
    autonomous systems, SD-WAN, subnets, and the control plane.

    Use this when the user asks a networking question and you need to find the most
    relevant passage(s) to answer from, rather than reading a whole article. It embeds
    the query and ranks every chunk in the corpus by semantic (meaning-based) similarity,
    so it can match a question even if it doesn't share exact wording with the source
    text. Returns the top_k best-matching chunks, each with the article title, section
    heading, the chunk's text, and a similarity_score (roughly 0-1, higher is more
    relevant).

    Args:
        query: A natural-language question or topic, e.g. "how does BGP pick a route"
            or "difference between control plane and data plane".
        top_k: How many results to return (default 3).
    """
    results = _search(query, top_k=top_k)
    if results:
        top = results[0]
        summary = (
            f"{len(results)} results; top match: "
            f"{top['article_title']} / {top['section_heading']} "
            f"(score={top['similarity_score']:.3f})"
        )
    else:
        summary = "0 results"
    _log_call("search", {"query": query, "top_k": top_k}, summary)
    return results


@mcp.tool()
def retrieve(article_id: str) -> str:
    """Fetch the full text of one complete article from the networking corpus.

    Use this when the user wants an entire article rather than just a snippet — for
    example, after search() surfaces a promising article and the user wants full
    context, or when they explicitly ask to read a whole article on a topic. Call
    list_docs() first if you don't already know the article_id.

    Args:
        article_id: The article's identifier, i.e. its source filename without
            ".txt" (e.g. "what-is-bgp", "what-is-a-router"). Get valid ids from
            list_docs().
    """
    try:
        text = _retrieve(article_id)
    except ValueError as e:
        _log_call("retrieve", {"article_id": article_id}, f"error: {e}")
        raise
    _log_call("retrieve", {"article_id": article_id}, f"returned {len(text)} chars")
    return text


@mcp.tool()
def list_docs() -> list[dict]:
    """List every article available in the networking corpus.

    Use this first when you don't know what topics the corpus covers, to find the
    right article_id to pass to retrieve(), or to give the user an overview of what
    knowledge is available. Returns, for each of the 9 articles, its article_id,
    title, and a one-line description.
    """
    docs = _list_docs()
    _log_call("list_docs", {}, f"{len(docs)} articles")
    return docs


if __name__ == "__main__":
    mcp.run()

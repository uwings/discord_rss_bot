#!/usr/bin/env python
"""KC 知识库语义查询小工具（走本地 Bridge，只读）。

用法: .venv/Scripts/python scripts/kc_query.py "查询语句" [top_k]
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

BRIDGE = "http://192.168.5.33:9100"
COLLECTION = "knowledge-base-vectors"
CLIENT_CFG = Path("D:/Hermes/projects/local-data-bridge/config/bridge-client-pc.yaml")


def main() -> None:
    query = sys.argv[1]
    top_k = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    token = re.search(r'token:\s*["\']?([^"\'\s]+)', CLIENT_CFG.read_text(encoding="utf-8")).group(1)

    body = json.dumps({"query": query, "top_k": top_k}).encode()
    req = urllib.request.Request(
        f"{BRIDGE}/vector/{COLLECTION}/query",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())

    results = data.get("data", {}).get("results") or []
    print(f"# 查询: {query}\n")
    for i, h in enumerate(results, 1):
        p = h.get("payload", {})
        profile = p.get("profile") or p.get("type") or ""
        snippet = p.get("body_snippet") or p.get("text") or json.dumps(p, ensure_ascii=False)
        print(f"--- [{i}] score={h.get('score', 0):.3f} profile={profile} ---")
        print(snippet[:700].replace("\\n", "\n"))
        print()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()

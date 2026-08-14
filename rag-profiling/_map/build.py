#!/usr/bin/env python
"""_map 생성기. 스킬 원본을 읽어 문서 참조 그래프를 만든다.

    python _map/build.py            생성
    python _map/build.py --check    원본과 어긋났으면 종료코드 1

원본은 고치지 않는다. 노드는 실재하는 .md 만 인정하므로
본문의 예시(`시행령.md` · `README.md` 등)는 자동으로 걸러진다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CARD_W, CARD_H = 300, 180
COL_GAP, ROW_GAP = 460, 230

NOTE = "문서참조그래프.md"
CANVAS = "구조.canvas"


def collect(root: Path) -> list[str]:
    """노드가 될 문서. 순서를 고정해야 --check 가 성립한다."""
    docs = ["SKILL.md"] + sorted(f"references/{p.name}" for p in root.glob("references/*.md"))
    return [d for d in docs if (root / d).exists()]


def collect_edges(root: Path, docs: list[str]) -> dict[tuple[str, str], int]:
    """A 가 B 의 파일명을 몇 번 적었는지. 언급을 참조로 본다."""
    by_name = {Path(d).name: d for d in docs}
    out: dict[tuple[str, str], int] = {}
    for src in docs:
        txt = (root / src).read_text(encoding="utf-8", errors="ignore")
        for name, dst in by_name.items():
            if dst == src:
                continue
            hits = len(re.findall(re.escape(name), txt))
            if hits:
                out[(src, dst)] = hits
    return dict(sorted(out.items()))


def depths(docs: list[str], edges: dict) -> dict[str, int]:
    """왼쪽에서 오른쪽으로 흐르게 할 층. 참조가 순환하므로 횟수로 끊는다.

    순환은 층 값을 노드 수만큼 부풀린다. 그대로 좌표로 쓰면 열 사이가
    수천 px 로 벌어지므로, 마지막에 연속 순위로 압축한다.
    """
    d = {doc: 0 for doc in docs}
    for _ in range(len(docs)):
        moved = False
        for src, dst in edges:
            if d[dst] < d[src] + 1:
                d[dst] = d[src] + 1
                moved = True
        if not moved:
            break
    rank = {v: i for i, v in enumerate(sorted(set(d.values())))}
    return {doc: rank[v] for doc, v in d.items()}


def build_canvas(docs: list[str], edges: dict, depth: dict) -> str:
    cols: dict[int, list[str]] = {}
    for doc in docs:
        cols.setdefault(depth[doc], []).append(doc)

    nodes, node_id = [], {}
    for col in sorted(cols):
        for row, doc in enumerate(cols[col]):
            nid = f"n{len(nodes) + 1}"
            node_id[doc] = nid
            node = {
                "id": nid,
                "type": "file",
                "file": doc,
                "x": col * COL_GAP,
                "y": row * ROW_GAP,
                "width": CARD_W,
                "height": CARD_H,
            }
            if doc == "SKILL.md":
                node["color"] = "5"
            nodes.append(node)

    out_edges = []
    for i, ((src, dst), hits) in enumerate(edges.items(), 1):
        edge = {
            "id": f"e{i}",
            "fromNode": node_id[src],
            "fromSide": "right",
            "toNode": node_id[dst],
            "toSide": "left",
        }
        if hits > 1:
            edge["label"] = str(hits)
        out_edges.append(edge)

    return json.dumps({"nodes": nodes, "edges": out_edges}, ensure_ascii=False, indent=2) + "\n"


def build_note(docs: list[str], edges: dict) -> str:
    def mid(doc: str) -> str:
        return Path(doc).stem.replace("-", "_")

    incoming = {doc: 0 for doc in docs}
    outgoing = {doc: 0 for doc in docs}
    for (src, dst), hits in edges.items():
        outgoing[src] += hits
        incoming[dst] += hits

    lines = [
        "# 문서 참조 그래프",
        "",
        f"노드 {len(docs)} · 엣지 {len(edges)}. 화살표는 왼쪽 문서가 오른쪽 문서를 가리킨다는 뜻이고,",
        "숫자는 언급 횟수다. 클릭해서 열려면 같은 폴더의 `구조.canvas` 를 쓴다.",
        "",
        f"**이 파일은 `_map/build.py` 가 만든다. 직접 고치지 않는다.**",
        "원본을 고쳤으면 `python _map/build.py` 로 다시 만든다.",
        "`python _map/build.py --check` 는 어긋났을 때 종료코드 1 을 낸다.",
        "",
        "```mermaid",
        "flowchart LR",
    ]
    for doc in docs:
        lines.append(f"  {mid(doc)}[\"{Path(doc).name}\"]")
    for (src, dst), hits in edges.items():
        arrow = f" -->|{hits}| " if hits > 1 else " --> "
        lines.append(f"  {mid(src)}{arrow}{mid(dst)}")
    lines += [
        "```",
        "",
        "## 참조가 몰리는 곳",
        "",
        "| 문서 | 들어오는 참조 | 나가는 참조 |",
        "|---|---:|---:|",
    ]
    for doc in sorted(docs, key=lambda d: (-incoming[d], d)):
        lines.append(f"| `{Path(doc).name}` | {incoming[doc]} | {outgoing[doc]} |")

    lines += ["", "## 엣지", "", "| 가리키는 쪽 | 가리켜지는 쪽 | 횟수 |", "|---|---|---:|"]
    for (src, dst), hits in sorted(edges.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| `{Path(src).name}` | `{Path(dst).name}` | {hits} |")

    lines += ["", "## 파일", ""]
    for doc in docs:
        lines.append(f"- [[{Path(doc).stem}]] `{doc}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="어긋났으면 종료코드 1")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    root = here.parent
    docs = collect(root)
    if len(docs) < 2:
        return int(bool(sys.stderr.write("[중단] 문서를 못 찾았다. 스킬 폴더 안에서 돌린다\n"))) or 1

    edges = collect_edges(root, docs)
    made = {NOTE: build_note(docs, edges), CANVAS: build_canvas(docs, edges, depths(docs, edges))}

    if args.check:
        stale = [n for n, body in made.items() if not (here / n).exists() or (here / n).read_text(encoding="utf-8") != body]
        if stale:
            print("[어긋남] " + " · ".join(stale) + " → python _map/build.py")
            return 1
        print(f"[일치] 노드 {len(docs)} · 엣지 {len(edges)}")
        return 0

    for name, body in made.items():
        (here / name).write_text(body, encoding="utf-8", newline="\n")
    print(f"[생성] 노드 {len(docs)} · 엣지 {len(edges)} → {NOTE} · {CANVAS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

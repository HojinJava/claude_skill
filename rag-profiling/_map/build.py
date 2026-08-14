#!/usr/bin/env python
"""_map 생성기. 스킬 원본을 읽어 문서 참조 그래프를 만든다.

    python _map/build.py            생성
    python _map/build.py --check    원본과 어긋났으면 종료코드 1

원본은 고치지 않는다. 노드는 실재하는 .md 만 인정하므로
본문의 예시(`시행령.md` · `README.md` 등)는 자동으로 걸러진다.

선을 줄이는 규칙 둘. 전부 그리면 9개 노드에 28선이라 안 읽힌다.
  1. 목차 문서(SKILL.md)의 참조는 그래프에서 뺀다. 9개를 다 가리키는 게
     정의라서 정보가 없고 화면만 덮는다. 표로 따로 적는다.
  2. 서로 가리키는 쌍은 한 선으로 합치고 양쪽에 화살촉을 단다.
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

INDEX = "SKILL.md"
NOTE = "문서참조그래프.md"
CANVAS = "구조.canvas"
FLOW = "진행.canvas"

PIPE_RE = re.compile(
    r"^\|\s*(준비 · 1회|조건부|루프)\s*\|\s*(\S+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$"
)


def collect(root: Path) -> list[str]:
    """노드가 될 문서. 순서를 고정해야 --check 가 성립한다."""
    docs = [INDEX] + sorted(f"references/{p.name}" for p in root.glob("references/*.md"))
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


def split_edges(edges: dict) -> tuple[dict, dict]:
    """목차가 내보내는 참조와 문서끼리의 참조를 가른다."""
    index = {k: v for k, v in edges.items() if k[0] == INDEX}
    body = {k: v for k, v in edges.items() if k[0] != INDEX and k[1] != INDEX}
    return index, body


def merge_mutual(body: dict) -> dict[tuple[str, str], tuple[int, int]]:
    """서로 가리키는 쌍은 한 선으로. 값은 (정방향, 역방향) 횟수."""
    merged: dict[tuple[str, str], tuple[int, int]] = {}
    taken: set[tuple[str, str]] = set()
    for (src, dst), hits in sorted(body.items()):
        if (src, dst) in taken:
            continue
        back = body.get((dst, src))
        if back is not None:
            taken.add((dst, src))
        merged[(src, dst)] = (hits, back or 0)
    return merged


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


def sides(xa: int, xb: int) -> tuple[str, str]:
    if xb > xa:
        return "right", "left"
    if xb < xa:
        return "left", "right"
    return "bottom", "top"


def existing_positions(path: Path) -> dict[str, dict]:
    """이미 있는 캔버스에서 카드 위치를 읽는다. 옵시디언에서 손으로
    옮긴 배치를 재생성이 덮어쓰지 않게 하기 위해서다."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out = {}
    for n in data.get("nodes", []):
        if n.get("type") == "file" and "file" in n:
            out[n["file"]] = {k: n[k] for k in ("x", "y", "width", "height") if k in n}
    return out


def build_canvas(docs: list[str], merged: dict, depth: dict, keep: dict[str, dict]) -> str:
    body_docs = [d for d in docs if d != INDEX]
    cols: dict[int, list[str]] = {}
    for doc in body_docs:
        cols.setdefault(depth[doc], []).append(doc)

    nodes, node_id, pos = [], {}, {}

    def place(doc: str, x: int, y: int, color: str | None = None) -> None:
        nid = f"n{len(nodes) + 1}"
        node_id[doc] = nid
        node = {"id": nid, "type": "file", "file": doc,
                "x": x, "y": y, "width": CARD_W, "height": CARD_H}
        node.update(keep.get(doc, {}))
        pos[doc] = node["x"]
        if color:
            node["color"] = color
        nodes.append(node)

    tallest = max((len(v) for v in cols.values()), default=1)
    if INDEX in docs:
        place(INDEX, -COL_GAP, (tallest - 1) * ROW_GAP // 2, color="5")

    for col in sorted(cols):
        for row, doc in enumerate(cols[col]):
            place(doc, col * COL_GAP, row * ROW_GAP)

    out_edges = []
    for i, ((src, dst), (fwd, back)) in enumerate(merged.items(), 1):
        from_side, to_side = sides(pos[src], pos[dst])
        edge = {
            "id": f"e{i}",
            "fromNode": node_id[src],
            "fromSide": from_side,
            "toNode": node_id[dst],
            "toSide": to_side,
        }
        if back:
            edge["fromEnd"] = "arrow"
            edge["label"] = f"{fwd}·{back}"
        elif fwd > 1:
            edge["label"] = str(fwd)
        out_edges.append(edge)

    return json.dumps({"nodes": nodes, "edges": out_edges}, ensure_ascii=False, indent=2) + "\n"


def build_note(docs: list[str], index: dict, body: dict, merged: dict) -> str:
    def mid(doc: str) -> str:
        return Path(doc).stem.replace("-", "_")

    body_docs = [d for d in docs if d != INDEX]
    incoming = {doc: 0 for doc in body_docs}
    outgoing = {doc: 0 for doc in body_docs}
    for (src, dst), hits in body.items():
        outgoing[src] += hits
        incoming[dst] += hits

    lines = [
        "# 문서 참조 그래프",
        "",
        f"문서 {len(body_docs)}개가 서로 가리키는 관계다. 선 {len(merged)}개.",
        "숫자는 언급 횟수이고, 양쪽에 화살촉이 있으면 서로 가리킨다는 뜻이다.",
        "클릭해서 열려면 같은 폴더의 `구조.canvas` 를 쓴다.",
        "",
        f"`{INDEX}` 의 참조는 그래프에서 뺐다. 목차라서 전부 가리키는 게 정의라,",
        "그리면 화면만 덮고 알려주는 것이 없다. 아래 표에 따로 적었다.",
        "",
        "**이 파일은 `_map/build.py` 가 만든다. 직접 고치지 않는다.**",
        "원본을 고쳤으면 `python _map/build.py` 로 다시 만든다.",
        "`python _map/build.py --check` 는 어긋났을 때 종료코드 1 을 낸다.",
        "",
        "```mermaid",
        "flowchart LR",
    ]
    for doc in body_docs:
        lines.append(f"  {mid(doc)}[\"{Path(doc).name}\"]")
    for (src, dst), (fwd, back) in merged.items():
        if back:
            lines.append(f"  {mid(src)} <-->|{fwd}·{back}| {mid(dst)}")
        elif fwd > 1:
            lines.append(f"  {mid(src)} -->|{fwd}| {mid(dst)}")
        else:
            lines.append(f"  {mid(src)} --> {mid(dst)}")
    lines += [
        "```",
        "",
        "## 참조가 몰리는 곳",
        "",
        "| 문서 | 들어오는 참조 | 나가는 참조 |",
        "|---|---:|---:|",
    ]
    for doc in sorted(body_docs, key=lambda d: (-incoming[d], d)):
        lines.append(f"| `{Path(doc).name}` | {incoming[doc]} | {outgoing[doc]} |")

    lines += ["", "## 엣지", "", "| 가리키는 쪽 | 가리켜지는 쪽 | 횟수 |", "|---|---|---:|"]
    for (src, dst), hits in sorted(body.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| `{Path(src).name}` | `{Path(dst).name}` | {hits} |")

    if index:
        lines += ["", f"## `{INDEX}` 가 가리키는 것", "", "| 가리켜지는 쪽 | 횟수 |", "|---|---:|"]
        for (_, dst), hits in sorted(index.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| `{Path(dst).name}` | {hits} |")

    lines += ["", "## 파일", ""]
    for doc in docs:
        lines.append(f"- [[{Path(doc).stem}]] `{doc}`")
    lines.append("")
    return "\n".join(lines)


def parse_pipeline(root: Path) -> list[dict]:
    """SKILL.md 파이프라인 표를 파싱한다. 표가 정본이고 진행 캔버스는 그 렌더다."""
    out = []
    for line in (root / INDEX).read_text(encoding="utf-8").splitlines():
        m = PIPE_RE.match(line)
        if m:
            out.append(dict(zip(("group", "stage", "job", "ref", "team"), m.groups())))
    return out


def _card_text(st: dict) -> str:
    """카드 본문. references/xxx.md 는 위키링크로 바꿔 클릭하면 원본이 열리게 한다."""
    ref = st["ref"]
    ref = re.sub(r"`references/([a-z-]+)\.md`", r"[[\1]]", ref)
    ref = ref.replace("이 문서", "[[SKILL]]").replace("`", "")
    job = st["job"].split(". ")
    lines = [f"**{st['stage']} · {job[0]}**"]
    if len(job) > 1:
        lines.append(". ".join(job[1:]))
    lines.append(ref)
    return "\n".join(lines)


def build_flow(stages: list[dict]) -> str:
    """단계 흐름 캔버스. 준비 행이 위, 루프 여덟이 고리로 돈다."""
    W, H, GX, GY = 340, 150, 420, 230
    nodes, edges, nid = [], [], {}

    def add(st: dict, x: int, y: int, color: str | None = None) -> None:
        i = f"n{len(nodes) + 1}"
        nid[st["stage"]] = i
        node = {"id": i, "type": "text", "text": _card_text(st),
                "x": x, "y": y, "width": W, "height": H}
        if color:
            node["color"] = color
        nodes.append(node)

    prep = [s for s in stages if s["group"] != "루프"]
    loop = [s for s in stages if s["group"] == "루프"]

    for i, st in enumerate(prep):
        add(st, i * GX, 0, color="4" if st["group"] == "조건부" else None)

    top, bottom = loop[:4], loop[4:]
    for i, st in enumerate(top):
        add(st, i * GX, 400)
    for i, st in enumerate(bottom):
        add(st, (len(top) - 1 - i) * GX, 400 + GY)

    def link(a: str, b: str, fs: str, ts: str, label: str | None = None) -> None:
        e = {"id": f"e{len(edges) + 1}", "fromNode": nid[a], "fromSide": fs,
             "toNode": nid[b], "toSide": ts}
        if label:
            e["label"] = label
        edges.append(e)

    for a, b in zip(prep, prep[1:]):
        link(a["stage"], b["stage"], "right", "left")
    if prep and loop:
        link(prep[-1]["stage"], loop[0]["stage"], "bottom", "top")
    for a, b in zip(loop, loop[1:]):
        sa, sb = a["stage"], b["stage"]
        if sb in [s["stage"] for s in top][1:] and sa in [s["stage"] for s in top]:
            link(sa, sb, "right", "left")
        elif sa in [s["stage"] for s in top]:
            link(sa, sb, "bottom", "top")
        else:
            link(sa, sb, "left", "right")
    if len(loop) > 1:
        link(loop[-1]["stage"], loop[0]["stage"], "top", "bottom", "보류 · 미해결이 다음 루프의 측정 항목")
        cond = [s for s in stages if s["group"] == "조건부"]
        if cond:
            link(loop[-1]["stage"], cond[0]["stage"], "left", "bottom", "기법이 늘면")

    if loop:
        xs = [n["x"] for n in nodes[len(prep):]]
        ys = [n["y"] for n in nodes[len(prep):]]
        nodes.append({"id": "grp-loop", "type": "group",
                      "label": "루프 · 한 번에 최대 4회",
                      "x": min(xs) - 40, "y": min(ys) - 60,
                      "width": max(xs) - min(xs) + W + 80,
                      "height": max(ys) - min(ys) + H + 100})

    return json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, indent=2) + "\n"


def canvas_meaning(text: str) -> tuple | None:
    """캔버스의 의미만 뽑는다. 좌표 · 크기 · 포맷은 비교하지 않는다.
    옵시디언이 파일을 다시 저장하거나 카드를 손으로 옮겨도 어긋남이 아니다."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    ident = {n["id"]: n.get("file") or n.get("text") or n.get("label")
             for n in data.get("nodes", [])}
    files = frozenset(f for f in ident.values() if f)
    edges = frozenset(
        (ident.get(e.get("fromNode")), ident.get(e.get("toNode")),
         e.get("label"), e.get("fromEnd"))
        for e in data.get("edges", [])
    )
    return files, edges


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="어긋났으면 종료코드 1")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    root = here.parent
    docs = collect(root)
    if len(docs) < 2:
        sys.stderr.write("[중단] 문서를 못 찾았다. 스킬 폴더 안에서 돌린다\n")
        return 1

    index, body = split_edges(collect_edges(root, docs))
    merged = merge_mutual(body)
    keep = existing_positions(here / CANVAS)
    made = {
        NOTE: build_note(docs, index, body, merged),
        CANVAS: build_canvas(docs, merged, depths([d for d in docs if d != INDEX], body), keep),
    }
    stages = parse_pipeline(root)
    if stages:
        made[FLOW] = build_flow(stages)

    if args.check:
        stale = []
        for name, text in made.items():
            cur = (here / name).read_text(encoding="utf-8") if (here / name).exists() else ""
            if name.endswith(".canvas"):
                if canvas_meaning(cur) != canvas_meaning(text):
                    stale.append(name)
            elif cur != text:
                stale.append(name)
        if stale:
            print("[어긋남] " + " · ".join(stale) + " → python _map/build.py")
            return 1
        print(f"[일치] 문서 {len(docs)} · 선 {len(merged)}")
        return 0

    for name, text in made.items():
        (here / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"[생성] 문서 {len(docs)} · 그래프 선 {len(merged)} (목차 참조 {len(index)}건은 표로)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

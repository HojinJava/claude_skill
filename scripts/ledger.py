"""측정 원장. 바퀴가 돌 때마다 파일이 새로 생기지 않고 레코드가 쌓인다.

문제: 바퀴마다 산출 파일이 새로 생기면(crosslink.json → crosslink2.json) 어느 값이 현행인지
      파일명으로만 짐작하게 되고, 값이 왜 바뀌었는지가 아무 데도 안 남는다.
해결: 한 파일(JSONL)에 덧붙이기만 한다. 옛 레코드를 지우지 않고 superseded_by 로 잇는다.
      값 옆에 why 가 함께 남아, 47.6% 가 73.3% 로 바뀐 이유를 다음 바퀴가 읽을 수 있다.

**첫 줄은 목차다.** 키 목록과 뜻을 담는다. 읽는 쪽이 전문을 훑지 않아도 되게 한다.

    python ledger.py init  out/ledger.jsonl
    python ledger.py add   out/ledger.jsonl --json '{"round":"R2", ...}'
    python ledger.py add   out/ledger.jsonl --file rec.json
    python ledger.py check out/ledger.jsonl              스키마 · 중복 · 끊긴 사슬 · 현행 충돌
    python ledger.py show  out/ledger.jsonl [--q Q7] [--all]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 목차 레코드. 첫 줄에 놓아 읽는 쪽이 키를 먼저 안다
INDEX = {
    "_": "index",
    "about": "코퍼스 프로파일링 측정 원장. 덧붙이기만 하고 지우지 않는다",
    "current": "superseded_by 가 null 인 레코드가 현행값이다. 문서에는 현행값만 인용한다",
    "keys": {
        "id": "고유 식별자. round.q 형식 권장 (R2.Q7)",
        "date": "YYYY-MM-DD. 측정한 날",
        "round": "바퀴 번호 (R1, R2 …)",
        "q": "측정 항목 또는 가설 (Q1~Q8 · H1~H4)",
        "title": "이 레코드가 말하는 것 한 줄",
        "src": "근거. 쿼리 파일 · DB · 산출 JSON 경로",
        "value": "측정값. 문자열로 단위까지 적는다",
        "denom": "분모. 비율이면 필수",
        "why": "이 값이 나온 이유 · 앞 레코드에서 바뀐 이유",
        "verdict": "채택 | 보류 | 기각 | 측정",
        "basis": "실측 | 오답비용 | 이미구현됨",
        "next_measure": "다음 바퀴에 우리 데이터로 잴 것",
        "next_research": "다음 바퀴에 밖에서 찾아볼 자료",
        "superseded_by": "이 레코드를 대체한 id. null 이면 현행",
    },
}

REQUIRED = ("id", "date", "round", "q", "title", "verdict")
VERDICTS = {"채택", "보류", "기각", "측정"}
BASES = {"실측", "오답비용", "이미구현됨", None, ""}


def read(path: Path) -> tuple[dict, list[dict]]:
    if not path.exists():
        sys.exit(f"[중단] 원장이 없다: {path} · 먼저 init")
    idx, recs = None, []
    for ln, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            o = json.loads(raw)
        except json.JSONDecodeError as e:
            sys.exit(f"[중단] {path}:{ln} JSON 아님 · {e}")
        (idx := o) if o.get("_") == "index" else recs.append(o)
    return idx, recs


def check(path: Path) -> int:
    idx, recs = read(path)
    bad = []
    if not idx:
        bad.append("첫 줄에 목차 레코드가 없다. 읽는 쪽이 키를 모른다")

    ids = {}
    for r in recs:
        rid = r.get("id", "?")
        for k in REQUIRED:
            if not r.get(k):
                bad.append(f"{rid}: 필수 키 없음 · {k}")
        if r.get("verdict") not in VERDICTS:
            bad.append(f"{rid}: verdict 가 {VERDICTS} 밖 · {r.get('verdict')!r}")
        if r.get("basis") not in BASES:
            bad.append(f"{rid}: basis 가 {BASES - {None, ''}} 밖 · {r.get('basis')!r}")
        # 비율을 적었으면 분모가 있어야 한다 (오류 1유형)
        v = str(r.get("value", ""))
        if "%" in v and not r.get("denom"):
            bad.append(f"{rid}: 비율인데 denom 이 없다 · {v}")
        if rid in ids:
            bad.append(f"{rid}: id 중복")
        ids[rid] = r

    # 대체 사슬이 끊기지 않았는지
    for rid, r in ids.items():
        s = r.get("superseded_by")
        if s and s not in ids:
            bad.append(f"{rid}: superseded_by 가 없는 id 를 가리킨다 · {s}")

    # 같은 q 에 현행이 둘이면 다음 사람이 틀린 것을 인용한다 (오류 6유형)
    cur = {}
    for r in recs:
        if r.get("superseded_by"):
            continue
        cur.setdefault(r["q"], []).append(r["id"])
    for q, lst in cur.items():
        if len(lst) > 1:
            bad.append(f"{q}: 현행 레코드가 {len(lst)}개 · {lst} · 하나만 남기고 superseded_by 를 채운다")

    print(f"레코드 {len(recs)} · 현행 {sum(1 for r in recs if not r.get('superseded_by'))}")
    for b in bad:
        print("  [결함]", b)
    print("통과" if not bad else f"실패 {len(bad)}건")
    return 1 if bad else 0


def add(path: Path, rec: dict) -> None:
    idx, recs = read(path)
    ids = {r["id"]: r for r in recs}
    if rec.get("id") in ids:
        sys.exit(f"[중단] id 중복 · {rec['id']}")
    rec.setdefault("superseded_by", None)
    # 같은 q 의 기존 현행을 자동으로 대체 처리한다. 손으로 하면 빠뜨린다
    stale = [r for r in recs if r["q"] == rec.get("q") and not r.get("superseded_by")]
    if stale:
        for r in stale:
            r["superseded_by"] = rec["id"]
        lines = [json.dumps(idx, ensure_ascii=False)] if idx else []
        lines += [json.dumps(r, ensure_ascii=False) for r in recs]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"  이전 현행 {len(stale)}건을 {rec['id']} 로 대체 표시")
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"추가 · {rec['id']}")


def show(path: Path, q: str | None, show_all: bool) -> None:
    _, recs = read(path)
    if q:
        recs = [r for r in recs if r["q"] == q]
    if not show_all:
        recs = [r for r in recs if not r.get("superseded_by")]
    for r in recs:
        mark = " " if not r.get("superseded_by") else "×"
        val = r.get("value", "")
        den = f" / {r['denom']}" if r.get("denom") else ""
        print(f"{mark} {r['id']:<10} {r['date']}  {r['q']:<4} {r.get('verdict',''):<3} {val}{den}")
        print(f"    {r['title']}")
        if r.get("why"):
            print(f"    why: {r['why']}")
        nx = " · ".join(x for x in (r.get("next_measure"), r.get("next_research")) if x)
        if nx:
            print(f"    next: {nx}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="측정 원장 (append-only JSONL)")
    ap.add_argument("cmd", choices=["init", "add", "check", "show"])
    ap.add_argument("path", type=Path)
    ap.add_argument("--json", help="레코드 JSON 문자열")
    ap.add_argument("--file", type=Path, help="레코드 JSON 파일 (객체 또는 배열)")
    ap.add_argument("--q", help="show: 이 항목만")
    ap.add_argument("--all", action="store_true", help="show: 대체된 것까지")
    a = ap.parse_args()

    if a.cmd == "init":
        if a.path.exists():
            sys.exit(f"[중단] 이미 있다 · {a.path}")
        a.path.parent.mkdir(parents=True, exist_ok=True)
        a.path.write_text(json.dumps(INDEX, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"생성 · {a.path}")
    elif a.cmd == "add":
        if not (a.json or a.file):
            sys.exit("[중단] --json 또는 --file 이 필요하다")
        raw = json.loads(a.json) if a.json else json.loads(a.file.read_text(encoding="utf-8"))
        for rec in (raw if isinstance(raw, list) else [raw]):
            add(a.path, rec)
    elif a.cmd == "check":
        sys.exit(check(a.path))
    else:
        show(a.path, a.q, a.all)


if __name__ == "__main__":
    main()

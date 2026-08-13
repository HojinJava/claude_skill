"""원장에서 문서의 세 절을 생성한다. 손으로 유지하던 것을 정본에서 뽑는다.

문제: 값 하나가 바뀌면 문서의 여러 곳을 손으로 세어 고쳐야 한다. 하나라도 빠뜨리면
      오류 8유형(문서 간 불일치)이고, 실제로 한 바퀴에 아홉 곳을 고친 적이 있다.
해결: 원장이 이미 들고 있는 것(판정 · 근거 · 다음에 잴 것)은 문서에서 지우고 여기서 뽑는다.
      문서에는 서사(실물 → 판단 → 안 그러면)만 손으로 남는다.

생성하는 자리는 셋이고 HTML 주석 표시 사이를 갈아 끼운다. 표시가 없으면 아무것도 안 한다.

    <!-- GEN:verdicts -->  …  <!-- /GEN:verdicts -->   판정표      kind=기법 인 현행 레코드
    <!-- GEN:open -->      …  <!-- /GEN:open -->       미해결      next_measure 가 있는 현행 레코드
    <!-- GEN:loopend -->   …  <!-- /GEN:loopend -->    종료 판정   바깥 입력을 기다리는 것

    python render.py ledger.jsonl report.html
    python render.py ledger.jsonl report.html --check   갈아 끼우지 않고 달라지는지만 본다

**닫힌 항목은 지우지 않는다.** 옛 레코드에 next_measure 가 있었는데 현행에 없으면
그 항목은 닫힌 것이므로 닫힘 구역에 남긴다. 지우면 왜 안 도는지가 사라진다.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

TAGS = {"채택": "ok", "보류": "hold", "기각": "no", "측정": "ev"}


def esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def load(path: Path):
    recs = []
    for ln, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            o = json.loads(raw)
        except json.JSONDecodeError as e:
            sys.exit(f"[중단] {path}:{ln} JSON 아님 · {e}")
        if o.get("_") != "index":
            recs.append(o)
    return recs


def sort_key(r: dict):
    """R1.01~R1.23 이 기법 카탈로그 순서다. 그 뒤에 나중에 붙은 것이 온다."""
    i = r["id"]
    if i.startswith("R1.") and i[3:].isdigit():
        return (0, int(i[3:]), "")
    return (1, 0, i)


def verdicts(cur: list) -> str:
    rows = sorted([r for r in cur if r.get("kind") == "기법"], key=sort_key)
    if not rows:
        return "<p>기법 판정 레코드가 없다(<code>kind</code> 가 안 달렸다).</p>"
    out = ['<div class="tblwrap"><table>',
           "<tr><th>기법</th><th>판정</th><th>근거</th><th>무엇이 정해졌나</th></tr>"]
    for r in rows:
        name = r.get("tech_name") or r["q"]
        val = r.get("value") or r.get("title") or ""
        basis = r.get("basis") or "·"
        btag = "ev" if basis == "실측" else ("cost" if basis == "오답비용" else "")
        bcell = (f'<span class="tag {btag}">{esc("비용 판단" if basis == "오답비용" else basis)}</span>'
                 if btag else "·")
        out.append(
            f'<tr><td>{esc(name)} <span class="nm">{esc(r["id"])}</span></td>'
            f'<td><span class="tag {TAGS.get(r["verdict"], "")}">{esc(r["verdict"])}</span></td>'
            f"<td>{bcell}</td>"
            f"<td>{esc(val)}</td></tr>")
    out.append("</table></div>")
    n = len(rows)
    ev = sum(1 for r in rows if r.get("basis") == "실측")
    out.append(f'<p class="src">원장 <code>ledger.jsonl</code> 에서 생성 · 기법 {n}건 중 근거가 실측인 것 {ev}건</p>')
    return "\n".join(out)


def open_items(recs: list, cur: list) -> str:
    """다음에 잴 것이 있는 항목. 바깥 입력이 필요한지로 가른다."""
    live = [r for r in cur if r.get("next_measure")]
    now = [r for r in live if not r.get("next_research")]
    wait = [r for r in live if r.get("next_research")]

    # 닫힌 것: 옛 레코드에 next_measure 가 있었는데 현행에는 없다
    had = {r["q"] for r in recs if r.get("superseded_by") and r.get("next_measure")}
    closed = [r for r in cur if r["q"] in had and not r.get("next_measure")]

    def table(items, third=None):
        """third 가 없으면 두 열이다. 같은 칸의 꼬리를 세 번째 열에 되풀이하지 않는다."""
        head = "<tr><th>항목</th><th>다음에 잴 것</th>" + ("<th>무엇이 있어야 풀리나</th></tr>"
                                                      if third else "</tr>")
        o = ['<div class="tblwrap"><table>', head]
        for r in items:
            extra = f'<td>{esc(r.get("next_research", ""))}</td>' if third else ""
            o.append(f'<tr><td>{esc(r["q"])} <span class="nm">{esc(r["id"])}</span></td>'
                     f'<td>{esc(r["next_measure"])}</td>{extra}</tr>')
        o.append("</table></div>")
        return "\n".join(o)

    out = [f"<p><b>다음에 잴 것이 남은 항목이 {len(live)}건</b>이다. "
           f"바깥 입력이 필요 없는 것이 <b>{len(now)}건</b>, 기다리는 것이 <b>{len(wait)}건</b>이다.</p>"]
    if now:
        out += ["<h3>지금 돌 수 있는 것</h3>",
                "<p>판정 기준이 서 있고 바깥에서 가져올 것이 없다. 다음 바퀴는 여기서 고른다. "
                "판정 기준은 <b>다음에 잴 것</b> 안에 함께 적혀 있다.</p>",
                table(now)]
    if wait:
        out += ["<h3>바깥 입력을 기다리는 것</h3>", table(wait, third=True)]
    if closed:
        out += ["<h3>닫힌 것</h3>",
                "<p>앞 바퀴가 남겼고 뒤 바퀴가 값을 냈다. <b>지우지 않는다.</b> "
                "왜 더 안 도는지가 여기 남아야 다음 사람이 같은 축을 다시 열지 않는다.</p>",
                '<div class="tblwrap"><table>',
                "<tr><th>항목</th><th>무엇으로 닫혔나</th><th>바퀴</th></tr>"]
        for r in closed:
            out.append(f'<tr><td>{esc(r["q"])} <span class="nm">{esc(r["id"])}</span></td>'
                       f'<td>{esc(r.get("title", ""))}</td><td class="n">{esc(r.get("round", ""))}</td></tr>')
        out += ["</table></div>"]
    out.append('<p class="src">원장 <code>ledger.jsonl</code> 에서 생성</p>')
    return "\n".join(out)


def loopend(cur: list) -> str:
    live = [r for r in cur if r.get("next_measure")]
    now = [r for r in live if not r.get("next_research")]
    wait = [r for r in live if r.get("next_research")]
    hold = [r for r in cur if r["verdict"] == "보류"]
    verdict = ("<b>더 돌 값어치가 있다.</b>" if now
               else "<b>더 돌 값어치가 낮다.</b> 남은 것이 전부 바깥 입력을 기다린다.")
    out = [f'<div class="note"><p class="ih">루프 종료 판정</p>{verdict} '
           f"현행 레코드 {len(cur)}건 중 다음에 잴 것이 남은 것이 {len(live)}건이고, "
           f"그중 <b>{len(now)}건은 바깥 입력 없이 지금 돌 수 있다</b>. "
           f"보류 판정은 {len(hold)}건이다.</div>"]
    if wait:
        # 목록은 미해결 절이 이미 들고 있다. 같은 넷을 두 번 보여주지 않는다.
        out.append(f"<p><b>바깥 입력을 기다리는 {len(wait)}건의 목록은 앞 절 미해결에 있다.</b> "
                   "여기서는 그 넷이 <b>왜 이 바퀴에서 안 돌았는지</b>만 가른다. "
                   "미해결이 “무엇이 남았나”라면 이 절은 “더 돌 값어치가 있나”다.</p>")
        kinds = {}
        for r in wait:
            k = (r.get("next_research") or "").split(".")[0][:40] or "·"
            kinds.setdefault(k, []).append(r["id"])
        out += ['<div class="tblwrap"><table>',
                "<tr><th>무엇을 기다리나</th><th>원장</th></tr>"]
        for k, ids in kinds.items():
            out.append(f'<tr><td>{esc(k)}</td><td class="n">{esc(" · ".join(ids))}</td></tr>')
        out += ["</table></div>"]
    out.append('<p class="src">원장 <code>ledger.jsonl</code> 에서 생성</p>')
    return "\n".join(out)


def splice(doc: str, name: str, body: str) -> tuple[str, bool]:
    a, b = f"<!-- GEN:{name} -->", f"<!-- /GEN:{name} -->"
    i, j = doc.find(a), doc.find(b)
    if i < 0 or j < 0 or j < i:
        print(f"  [건너뜀] {name} · 표시가 없다")
        return doc, False
    new = doc[:i + len(a)] + "\n" + body + "\n" + doc[j:]
    return new, new != doc


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="원장에서 판정표 · 미해결 · 종료 판정을 생성한다")
    ap.add_argument("ledger", type=Path)
    ap.add_argument("doc", type=Path)
    ap.add_argument("--check", action="store_true", help="갈아 끼우지 않고 달라지는지만 본다")
    a = ap.parse_args()

    recs = load(a.ledger)
    cur = [r for r in recs if not r.get("superseded_by")]
    doc = a.doc.read_text(encoding="utf-8")

    changed = False
    for name, body in (("verdicts", verdicts(cur)), ("open", open_items(recs, cur)),
                       ("loopend", loopend(cur))):
        doc, ch = splice(doc, name, body)
        changed |= ch
        print(f"  {name}: {'갱신' if ch else '그대로'}")

    if a.check:
        print("달라진다" if changed else "달라질 것 없다")
        sys.exit(1 if changed else 0)
    if changed:
        a.doc.write_text(doc, encoding="utf-8")
        print(f"→ {a.doc}")
    else:
        print("바뀐 것이 없어 안 썼다")


if __name__ == "__main__":
    main()

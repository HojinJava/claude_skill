"""측정 · 적재된 DB 에 쿼리를 돌린다.

로컬 DB 를 쓰는 이유가 여기 있다. 측정 항목이 늘어도 스크립트를 새로 짜지 않고
쿼리만 추가한다. .sql 파일은 세미콜론으로 나눠 순서대로 실행하고 각각 표로 찍는다.

    python q.py out/corpus.duckdb queries/basics.sql
    python q.py out/corpus.duckdb -e "SELECT ext, count(*) FROM doc GROUP BY 1"
    python q.py out/corpus.duckdb -e "..." --json out/result.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import duckdb
except ImportError:
    sys.exit("[중단] pip install duckdb")

MAX_ROWS = 40
MAX_CELL = 60


def cell(v) -> str:
    if v is None:
        return "·"
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    s = str(v).replace("\n", "\\n")
    return s if len(s) <= MAX_CELL else s[: MAX_CELL - 1] + "…"


def show(title: str, cols: list[str], rows: list[tuple]) -> None:
    if title:
        print(f"\n── {title}")
    if not rows:
        print("   (행 없음)")
        return
    shown = rows[:MAX_ROWS]
    grid = [cols] + [[cell(v) for v in r] for r in shown]
    w = [max(len(g[c]) for g in grid) for c in range(len(cols))]
    print("   " + "  ".join(h.ljust(w[i]) for i, h in enumerate(cols)))
    print("   " + "  ".join("-" * w[i] for i in range(len(cols))))
    for g in grid[1:]:
        print("   " + "  ".join(g[i].ljust(w[i]) for i in range(len(cols))))
    if len(rows) > MAX_ROWS:
        print(f"   … {len(rows) - MAX_ROWS:,}행 더 (전체는 --json 으로)")


def split_statements(text: str) -> list[str]:
    """`;` 로 나누되 문자열 리터럴·주석 안의 `;` 는 건너뛴다.
    정규식에 `;` 가 들어가는 일이 흔해서(예: '[^,;\\n]'), 단순 split 은 문장을 두 동강 낸다."""
    out, buf, i, n = [], [], 0, len(text)
    quote = False
    while i < n:
        c = text[i]
        if quote:
            buf.append(c)
            if c == "'":
                if i + 1 < n and text[i + 1] == "'":   # '' 는 escape 된 따옴표
                    buf.append("'")
                    i += 1
                else:
                    quote = False
        elif c == "'":
            quote = True
            buf.append(c)
        elif c == "-" and text[i + 1:i + 2] == "-":     # 줄 끝까지 주석
            j = text.find("\n", i)
            j = n if j < 0 else j
            buf.append(text[i:j])
            i = j - 1
        elif c == ";":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    if "".join(buf).strip():
        out.append("".join(buf))
    return out


def split_sql(text: str) -> list[tuple[str, str]]:
    """(제목, SQL). 직전 주석 줄을 제목으로 쓴다."""
    out, title = [], ""
    for chunk in split_statements(text):
        if not chunk.strip():
            continue
        lines = chunk.strip().splitlines()
        heads = [l.strip("-# ").strip() for l in lines if l.strip().startswith("--")]
        body = "\n".join(l for l in lines if not l.strip().startswith("--")).strip()
        if not body:
            continue
        title = heads[0] if heads else title
        out.append((title, body))
    return out


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="적재된 DB 에 측정 쿼리를 돌린다")
    ap.add_argument("db", type=Path)
    ap.add_argument("sql", type=Path, nargs="?", help=".sql 파일")
    ap.add_argument("-e", "--exec", dest="inline", help="인라인 SQL")
    ap.add_argument("--json", type=Path, help="전체 결과를 JSON 으로 저장")
    ap.add_argument("--write", action="store_true",
                    help="쓰기 모드. 파생 단위(조각 테이블 등)를 만들 때만 쓴다")
    a = ap.parse_args()

    if not a.db.exists():
        sys.exit(f"[중단] DB 가 없다: {a.db}. 먼저 load.py 를 돌린다")
    if not a.sql and not a.inline:
        sys.exit("[중단] .sql 파일이나 -e 중 하나가 필요하다")

    text = a.inline if a.inline else a.sql.read_text(encoding="utf-8")
    stmts = split_sql(text)
    con = duckdb.connect(str(a.db), read_only=not a.write)

    dump = []
    for title, sql in stmts:
        try:
            rel = con.sql(sql)
            if rel is None:                          # CREATE·ALTER 등 결과가 없는 문장
                print(f"\n── {title or '(무제)'}\n   실행됨 (결과 없음)")
                dump.append({"title": title, "sql": sql, "columns": [], "rows": []})
                continue
            cols = rel.columns
            rows = rel.fetchall()
        except Exception as e:                       # 쿼리 하나가 죽어도 나머지는 돈다
            print(f"\n── {title or '(무제)'}\n   [실패] {e}")
            dump.append({"title": title, "sql": sql, "error": str(e)})
            continue
        show(title, cols, rows)
        dump.append({
            "title": title, "sql": sql, "columns": cols,
            "rows": [[None if v is None else v for v in r] for r in rows],
        })
    con.close()

    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(
            json.dumps(dump, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"\n→ {a.json}")


if __name__ == "__main__":
    main()

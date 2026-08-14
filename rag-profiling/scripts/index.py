"""파생 인덱스를 1회만 만든다. 줄머리 마커는 `tok`, frontmatter 는 `meta` 로 편다.
이후 측정 질문은 원문 전수 스캔을 안 한다.

문제: 측정 항목이 늘 때마다 새 정규식을 `body` 전체(수억 자)에 건다. 항목이 30개면 전수 스캔이 30번이다.
해결: 마커가 될 만한 줄머리만 한 번에 뽑아 쌓아둔다. frontmatter 도 같이 key/val 로 펴둔다.

이득의 크기(실측, 분자·분모를 둘 다 문자로 맞춰서 잰 값):
  법령  tok 1,109,694행 = 35,028,437자 / 원문 127,194,318자 = 27.5%
  판례  tok 2,213,149행 = 42,213,650자 / 원문 586,670,534자 =  7.2%
  즉 스캔 대상이 원문 문자의 7~28%(코퍼스마다 다르다) 로 줄고, 한 행이 50자 이하라
  정규식이 긴 본문이 아니라 짧은 문자열에만 걸린다. "원문의 1% 미만"이 아니다.

**tok 의 경계**: 줄머리만 담는다. 문장 중간의 표현은 없다.
  "제N조 헤딩이 몇 개인가"  → tok (정확)
  "본문에 별표가 몇 번 나오나" → doc (tok 을 쓰면 줄머리에 걸린 것만 세어 조용히 적게 나온다)
  raw 는 마커 접두 + 39자까지다. 실측 최대는 법령 45자·판례 50자.
  skel 은 raw 를 치환한 뒤 26자에서 자른다. 27자째부터 갈리는 마커는 같은 skel 로 묶인다.
  skel 을 쓰는 tok_skel·tok_variant 도 이 26자 경계를 그대로 물려받는다.

**meta 의 경계**: 들여쓰기 없는 줄을 첫 콜론 하나로 자를 뿐이다. YAML 파서가 아니다.
  아래는 행이 안 나온다: 들여쓴 중첩 키 · 리스트 항목(`- 값`) · 여러 줄 값(`|` `>`) · 인라인
  `[]` `{}` 의 원소. 값이 리스트인 키는 키만 남고 val = '' 이 된다.
  버리는 양이 코퍼스마다 크게 다르다(실측, 펜스·빈 줄 제외):
    법령  meta 73,737행 · 버린 줄 244,772개 (들여쓴 줄 199,235 + 리스트 항목 45,537)
    판례  meta 1,090,024행 · 버린 줄 11개
  법령은 `첨부파일:` 아래에 별표 목록이 중첩으로 달려서 버린 쪽이 3배 넘게 많다.
  그래서 법령의 `첨부파일` 은 meta 에서 2,969건이 val = '' 로 보이지만 실제로는 값이 있다.
  "첨부파일이 비어 있다"고 읽으면 틀린다. 중첩이 걸린 키는 doc.fm_raw 를 직접 봐야 한다.
  fm_raw 가 없는 문서도 행이 없다. 결측률 분모는 meta 가 아니라 doc 이다(META 위 주석 참고).

    python index.py out/corpus.duckdb [--top 15]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import duckdb
except ImportError:
    sys.exit("[중단] pip install duckdb")

ENUM = "①-⑳㉑-㉟❶-❿ⅰ-ⅹⅠ-Ⅴⓐ-ⓔ㉮-㉱"

# 줄머리가 마커처럼 생긴 줄만 한 패스로 뽑는다.
# 줄 단위로 쪼개면(str_split) 수억 자를 수천만 원소의 리스트로 물어야 한다. 통째로 정규식을 건다.
HEAD = r"(?m)^(?:#{1,6} |[^가-힣A-Za-z0-9[:space:]]|[0-9]+[.)\\]|제[0-9]+)[^\n]{0,39}"

BUILD = f"""
CREATE OR REPLACE TABLE tok AS
WITH x AS (
    SELECT doc_id, unnest(regexp_extract_all(body, '{HEAD}')) AS raw
    FROM doc WHERE load_ok
)
SELECT doc_id,
       row_number() OVER (PARTITION BY doc_id) AS seq,
       raw,
       substr(regexp_replace(
                regexp_replace(raw, '[0-9]+', '<N>', 'g'),
                '[{ENUM}]+', '<E>', 'g'), 1, 26) AS skel,
       try_cast(regexp_extract(raw, '([0-9]+)', 1) AS INTEGER) AS num,
       length(regexp_extract(raw, '^(#+)', 1)) AS hlevel
FROM x;

-- 골격별 요약. 새 측정을 설계할 때 여기부터 본다
CREATE OR REPLACE VIEW tok_skel AS
SELECT skel, count(*) AS lines, count(DISTINCT doc_id) AS docs,
       round(count(DISTINCT doc_id) * 100.0
             / (SELECT count(*) FROM doc WHERE load_ok), 1) AS docs_pct
FROM tok GROUP BY skel;

-- 공백만 다른 골격을 묶는다. 정규식을 한 형태로 쓰면 나머지를 놓친다.
-- 문서 2개 이상에 나오고 공백만으로 이뤄지지 않은 것만 남긴다
CREATE OR REPLACE VIEW tok_variant AS
SELECT norm, count(DISTINCT skel) AS variants, sum(lines) AS lines, sum(docs) AS docs,
       string_agg(DISTINCT skel, ' | ') AS forms
FROM (
    SELECT trim(replace(replace(skel, ' ', ''), chr(9), '')) AS norm, skel, lines, docs
    FROM tok_skel WHERE docs >= 2
)
WHERE length(norm) >= 2
GROUP BY norm HAVING count(DISTINCT skel) > 1;
"""

# load.py 는 frontmatter 를 fm_raw 에 통째로 넣기만 한다. 여기서 key/val 로 편다.
# 들여쓰기 없이 시작하고 콜론이 있는 줄만 본다. `-` `#` 로 시작하는 줄은 값·주석이라 뺀다.
# 콜론은 첫 개만 자른다. 값에 콜론이 들어간 URL(`출처: https://...`)이 쪼개지지 않게 한다.
KV = r"^([^\s:#-][^:]*):(.*)$"

# 함정: fm_raw 가 비었거나 NULL 인 문서는 meta 에 행이 아예 없다.
#   그래서 결측률을 meta 안에서만 재면 분모가 "frontmatter 가진 문서"로 좁아져 실제보다 좋게 나온다.
#   분모는 반드시 doc 을 쓴다.
#     SELECT count(DISTINCT doc_id) FILTER (WHERE key = '공포일자') * 100.0
#            / (SELECT count(*) FROM doc WHERE load_ok) AS 채움률 FROM meta;
#   키가 있고 값만 빈 경우(`법령분야: ''`)는 val = '' 인 행으로 남는다. 결측을 셀 때 같이 센다.
META = f"""
CREATE OR REPLACE VIEW meta AS
SELECT doc_id, key, val FROM (
    SELECT doc_id,
           trim(regexp_extract(raw, '{KV}', 1)) AS key,
           -- 앞뒤 공백을 벗기고, 값을 감싼 따옴표를 벗기고, 남은 공백을 다시 벗긴다
           trim(trim(trim(regexp_extract(raw, '{KV}', 2)), '''"')) AS val
    FROM (
        SELECT doc_id, unnest(str_split(fm_raw, chr(10))) AS raw
        FROM doc WHERE load_ok AND fm_raw IS NOT NULL AND fm_raw <> ''
    )
) WHERE key <> '';
"""


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="줄머리 마커(tok) · frontmatter(meta) 인덱스 생성")
    ap.add_argument("db", type=Path)
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()

    if not a.db.exists():
        sys.exit(f"[중단] DB 가 없다: {a.db} · 먼저 load.py 를 돌린다")

    con = duckdb.connect(str(a.db))
    con.execute(BUILD)
    con.execute(META)
    rows, docs, tok_chars, maxlen = con.sql(
        "SELECT count(*), count(DISTINCT doc_id),"
        " coalesce(sum(length(raw)), 0), coalesce(max(length(raw)), 0) FROM tok"
    ).fetchone()
    all_docs, chars = con.sql(
        "SELECT count(*), coalesce(sum(n_chars), 0) FROM doc WHERE load_ok"
    ).fetchone()
    print(f"tok {rows:,}행 · 문서 {docs:,}개 · 한 행 최대 {maxlen}자")
    # 분모·분자를 둘 다 문자로 맞춘다. 행 수를 문자 수로 나누면 뜻이 없는 비율이 나온다
    print(f"  마커 질문이 원문 {chars:,}자 대신 tok {tok_chars:,}자를 읽는다 "
          f"({tok_chars * 100 / max(1, chars):.1f}%)")

    fm_docs, meta_rows, n_keys = con.sql(
        "SELECT count(DISTINCT doc_id), count(*), count(DISTINCT key) FROM meta"
    ).fetchone()
    print(f"\nmeta {meta_rows:,}행 · 키 {n_keys}종 · frontmatter 가 있는 문서 "
          f"{fm_docs:,}/{all_docs:,} ({fm_docs * 100 / max(1, all_docs):.1f}%)")
    for key, fill, nv in con.sql(
        f"SELECT key, count(DISTINCT doc_id) * 100.0 / {max(1, all_docs)}, count(DISTINCT val)"
        " FROM meta GROUP BY key ORDER BY 2 DESC, 3 DESC LIMIT 6"
    ).fetchall():
        print(f"  {fill:5.1f}% 채움  값 {nv:>7,}종  {key}")

    print(f"\n상위 골격 {a.top}개")
    for skel, lines, dpct in con.sql(
        f"SELECT skel, lines, docs_pct FROM tok_skel ORDER BY docs DESC LIMIT {a.top}"
    ).fetchall():
        print(f"  {dpct:5.1f}%  {lines:>10,}줄  {skel!r}")

    n_var = con.sql("SELECT count(*) FROM tok_variant").fetchone()[0]
    print(f"\n표기 변종 {n_var}그룹 (정규식을 한 형태로 쓰면 나머지를 놓친다)")
    for norm, v, lines, forms in con.sql(
        "SELECT norm, variants, lines, forms FROM tok_variant ORDER BY lines DESC LIMIT 6"
    ).fetchall():
        print(f"  {v}종 {lines:>9,}줄  {forms[:74]}")
    con.close()
    print('\n다음: q.py <db> -e "SELECT * FROM tok_skel ORDER BY lines DESC LIMIT 20"')
    print('      q.py <db> -e "SELECT key, count(*) n, count(DISTINCT val) nv '
          'FROM meta GROUP BY 1 ORDER BY 2 DESC"')


if __name__ == "__main__":
    main()

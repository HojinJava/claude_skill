"""L단계 · 폴더를 로컬 DuckDB 로 적재한다. 1회만 하고, 이후 측정은 쿼리만 추가한다.

지키는 것:
  - 개행을 LF 로 정규화한다. CRLF 를 그대로 두면 문자 수가 부풀려지고
    길이·비용 추정이 전부 어긋난다. 정규화 전후 값을 _meta 에 남긴다.
  - 인코딩 실패 파일을 버리지 않고 카운트한다. 그 자체가 측정 결과다.
  - 파생 컬럼은 최소만 만든다. 파싱을 적재에 밀어넣으면 파서를 고칠 때마다 재적재해야 한다.

두 경로가 있다.
  fast  DuckDB 가 파일을 직접 읽는다. UTF-8 코퍼스면 이쪽. 수십 배 빠르다.
  safe  Python 이 인코딩을 골라가며 읽는다. fast 가 실패하면 자동으로 떨어진다.
둘 다 같은 스키마를 만든다.

    python load.py <folder> --db out/corpus.duckdb --name mycorpus [--glob "**/*.md"]
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import duckdb
except ImportError:
    sys.exit("[중단] pip install duckdb")

SKIP_DIR = {".git", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".idea"}
ENCODINGS = ("utf-8", "utf-8-sig", "cp949", "euc-kr", "cp1252")
BATCH = 2000

COLUMNS = """
    doc_id     INTEGER,
    rel_path   VARCHAR,
    dir        VARCHAR,
    name       VARCHAR,
    ext        VARCHAR,
    depth      INTEGER,
    sibling_n  INTEGER,   -- 같은 폴더의 파일 수. 문서 묶음 판별에 쓴다
    encoding   VARCHAR,
    load_ok    BOOLEAN,
    hash       VARCHAR,
    n_bytes    BIGINT,
    n_chars    BIGINT,    -- LF 정규화 후
    n_lines    INTEGER,
    fm_raw     VARCHAR,   -- frontmatter 블록 원문. 파싱은 쿼리에서
    body       VARCHAR    -- 전체 원문(정규화만). 원본을 재는 게 원칙이라 자르지 않는다
"""

# frontmatter 를 뺀 본문. 원본을 건드리지 않고 필요할 때만 쓴다
VIEW = """
CREATE OR REPLACE VIEW doc_text AS
SELECT *, CASE WHEN fm_raw IS NULL THEN body
               ELSE substr(body, length(fm_raw) + 1) END AS text
FROM doc;
"""

# ── fast 경로 ────────────────────────────────────────────────────────────────
# read_text 가 파일을 직접 읽고, 정규화·파생을 전부 SQL 에서 끝낸다.
FAST = """
CREATE OR REPLACE TABLE doc AS
WITH src AS (
    SELECT replace(filename, '\\', '/') AS abs_path,
           replace(replace(content, chr(13) || chr(10), chr(10)), chr(13), chr(10)) AS body,
           length(content) AS chars_before
    FROM read_text($glob)
), base AS (
    SELECT ltrim(replace(abs_path, $root, ''), '/') AS rel_path, body, chars_before
    FROM src
), shaped AS (
    SELECT rel_path,
           CASE WHEN position('/' IN reverse(rel_path)) = 0 THEN ''
                ELSE substr(rel_path, 1, length(rel_path) - position('/' IN reverse(rel_path))) END AS dir,
           regexp_extract(rel_path, '([^/]+)$', 1) AS name,
           lower(coalesce(nullif(regexp_extract(rel_path, '(\\.[^./]+)$', 1), ''), '')) AS ext,
           length(rel_path) - length(replace(rel_path, '/', '')) AS depth,
           md5(body) AS hash,
           octet_length(encode(body)) AS n_bytes,
           length(body) AS n_chars,
           chars_before,
           length(body) - length(replace(body, chr(10), '')) + 1 AS n_lines,
           nullif(regexp_extract(body, '(?s)^(---|\\+\\+\\+)\\n.*?\\n(---|\\+\\+\\+)\\n', 0), '') AS fm_raw,
           body
    FROM base
)
SELECT (row_number() OVER (ORDER BY rel_path) - 1)::INTEGER AS doc_id,
       rel_path, dir, name, ext, depth,
       count(*) OVER (PARTITION BY dir)::INTEGER AS sibling_n,
       'utf-8' AS encoding, TRUE AS load_ok,
       hash, n_bytes, n_chars, n_lines::INTEGER AS n_lines, fm_raw, body,
       chars_before
FROM shaped;
"""


def decode(raw: bytes) -> tuple[str | None, str]:
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return None, "decode-failed"


def split_frontmatter(body: str) -> str | None:
    """앞머리 --- / +++ 블록을 원문 그대로 돌려준다. 없으면 None."""
    if not body.startswith(("---\n", "+++\n")):
        return None
    fence = body[:3]
    end = body.find(f"\n{fence}\n", 3)
    if end < 0:
        return None
    return body[: end + len(fence) + 2]


def collect(root: Path, pattern: str) -> list[Path]:
    return sorted(
        p for p in root.glob(pattern)
        if p.is_file() and not any(part in SKIP_DIR for part in p.parts)
    )


def load_fast(con, root: Path, pattern: str) -> Counter:
    """DuckDB 가 파일을 직접 읽는다. 정규화 전 문자 수도 같은 패스에서 뽑고 컬럼은 버린다."""
    # root 는 glob 에 넘긴 것과 같은 형태여야 한다. resolve() 하면 read_text 가 돌려주는
    # 상대 경로와 안 맞아 접두어가 안 잘리고 rel_path·depth 가 통째로 어긋난다.
    con.execute(FAST, {"glob": (root / pattern).as_posix(),
                       "root": root.as_posix()})
    n, chars, before, nbytes = con.sql(
        "SELECT count(*), sum(n_chars), sum(chars_before), sum(n_bytes) FROM doc"
    ).fetchone()
    con.execute("ALTER TABLE doc DROP COLUMN chars_before;")
    return Counter({"ok": n, "fail": 0, "chars": chars or 0, "bytes": nbytes or 0,
                    "cr_removed": (before or 0) - (chars or 0), "enc:utf-8": n})


def load_safe(con, root: Path, pattern: str) -> Counter:
    files = collect(root, pattern)
    if not files:
        sys.exit(f"[중단] 매칭되는 파일이 없다: {root} / {pattern}")
    sib: dict[Path, int] = defaultdict(int)
    for p in files:
        sib[p.parent] += 1

    con.execute(f"CREATE OR REPLACE TABLE doc ({COLUMNS});")
    ins = "INSERT INTO doc VALUES (" + ",".join(["?"] * 15) + ")"
    stat: Counter = Counter()
    rows: list[tuple] = []

    for i, p in enumerate(files):
        raw = p.read_bytes()
        text, enc = decode(raw)
        stat[f"enc:{enc}"] += 1
        rel = p.relative_to(root).as_posix()
        parts = rel.split("/")
        head = (i, rel, "/".join(parts[:-1]), p.name, p.suffix.lower(),
                len(parts) - 1, sib[p.parent], enc)

        if text is None:
            stat["fail"] += 1
            rows.append((*head, False, hashlib.md5(raw).hexdigest(),
                         len(raw), 0, 0, None, None))
        else:
            body = text.replace("\r\n", "\n").replace("\r", "\n")
            stat["cr_removed"] += len(text) - len(body)
            stat["ok"] += 1
            stat["chars"] += len(body)
            stat["bytes"] += len(raw)
            rows.append((*head, True, hashlib.md5(raw).hexdigest(),
                         len(raw), len(body), body.count("\n") + 1,
                         split_frontmatter(body), body))

        if len(rows) >= BATCH:
            con.executemany(ins, rows)
            rows.clear()
            print(f"  ... {i + 1:,}/{len(files):,}", end="\r", flush=True)
    if rows:
        con.executemany(ins, rows)
    return stat


def load(root: Path, pattern: str, db: Path, name: str, force_safe: bool) -> dict:
    db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db))
    con.execute("CREATE OR REPLACE TABLE _meta (k VARCHAR, v VARCHAR);")

    mode = "safe"
    if force_safe:
        stat = load_safe(con, root, pattern)
    else:
        try:
            stat = load_fast(con, root, pattern)
            mode = "fast"
        except Exception as e:
            print(f"  [fast 실패 → safe 로 전환] {str(e).splitlines()[0][:120]}")
            stat = load_safe(con, root, pattern)

    con.execute(VIEW)
    n_files = con.sql("SELECT count(*) FROM doc").fetchone()[0]
    meta = {
        "corpus": name,
        "root": str(root),
        "pattern": pattern,
        "mode": mode,
        "loaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_files": str(n_files),
        "n_ok": str(stat["ok"]),
        "n_fail": str(stat["fail"]),
        "bytes_total": str(stat["bytes"]),
        "chars_lf": str(stat["chars"]),
        "chars_before_normalize": str(stat["chars"] + stat["cr_removed"]),
        "cr_removed": str(stat["cr_removed"]),
        "encodings": ", ".join(
            f"{k[4:]}={v}" for k, v in sorted(stat.items()) if k.startswith("enc:")
        ),
    }
    con.executemany("INSERT INTO _meta VALUES (?, ?)", list(meta.items()))
    con.close()
    return meta


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="폴더 → 로컬 DuckDB 적재")
    ap.add_argument("folder", type=Path)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--name", default="corpus")
    ap.add_argument("--glob", default="**/*", help='기본 "**/*" · 예: "**/*.md"')
    ap.add_argument("--safe", action="store_true",
                    help="DuckDB 직독을 건너뛰고 Python 인코딩 폴백으로 적재")
    a = ap.parse_args()

    if not a.folder.is_dir():
        sys.exit(f"[중단] 폴더가 아니다: {a.folder}")

    m = load(a.folder, a.glob, a.db, a.name, a.safe)

    print(" " * 44, end="\r")
    print(f"적재 {m['n_ok']}/{m['n_files']} ({m['mode']}) · 실패 {m['n_fail']} · 인코딩 {m['encodings']}")
    print(f"문자 {int(m['chars_lf']):,} (LF 정규화)")
    cr = int(m["cr_removed"])
    if cr > 0:
        print(f"  정규화 전 {int(m['chars_before_normalize']):,} · CR {cr:,}자 제거 "
              f"(+{cr * 100 / int(m['chars_lf']):.1f}% 부풀림을 걷어냄)")
    if int(m["n_fail"]):
        print(f"  [주의] 디코딩 실패 {m['n_fail']}건. load_ok=false 로 남아 있다. 버리지 말고 원인을 본다")
    print(f"→ {a.db}\n")
    print("다음: python q.py <db> queries/basics.sql")


if __name__ == "__main__":
    main()

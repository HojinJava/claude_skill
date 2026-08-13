-- 1c · 예상 밖 값 탐지. 사전 지식으로 예상하지 못한 것을 스크립트가 신고하게 한다.
-- 여기서 걸린 것이 2차·3차 측정 항목이 된다.

-- [1] 인코딩 · 적재 실패. 버리지 말고 원인을 본다. 그 자체가 측정 결과다
SELECT encoding, load_ok, count(*) AS n
FROM doc GROUP BY 1, 2 ORDER BY load_ok, n DESC;

-- [2] 분포의 꼬리 · 가장 큰 문서. 청킹 상한과 컨텍스트 모델을 여기서 정한다
SELECT rel_path, n_chars, n_lines FROM doc WHERE load_ok
ORDER BY n_chars DESC LIMIT 10;

-- [3] 분포의 꼬리 · 가장 작은 문서. 스텁·빈 파일·플레이스홀더가 여기 숨는다
SELECT rel_path, n_chars, n_lines FROM doc WHERE load_ok AND n_chars > 0
ORDER BY n_chars ASC LIMIT 10;

-- [4] 빈 문서. 있으면 적재 범위(Q5)에서 뺄 후보다
SELECT count(*) AS empty_docs FROM doc WHERE load_ok AND n_chars < 10;

-- [5] 메타 키별 값 분포. distinct=1 이면 필터로 못 쓴다(한 값이 100%)
--     top_pct 가 95 이상이어도 사실상 필터가 아니다
WITH kv AS (
  SELECT doc_id, trim(regexp_extract(line, '^([^:]+):', 1)) AS k,
         trim(regexp_extract(line, '^[^:]+:(.*)$', 1)) AS v
  FROM (SELECT doc_id, unnest(str_split(fm_raw, chr(10))) AS line
        FROM doc WHERE fm_raw IS NOT NULL)
  WHERE regexp_matches(line, '^[^\s:#-][^:]{0,40}:')
),
agg AS (
  SELECT k, count(*) AS n, count(DISTINCT v) AS n_distinct,
         max(cnt) AS top_n
  FROM (SELECT k, v, count(*) OVER (PARTITION BY k, v) AS cnt FROM kv)
  GROUP BY k
)
SELECT k, n, n_distinct, round(top_n * 100.0 / n, 1) AS top_pct,
       CASE WHEN n_distinct = 1 THEN '필터 불가 · 한 값이 100%'
            WHEN top_n * 100.0 / n >= 95 THEN '사실상 필터 불가'
            ELSE '' END AS note
FROM agg ORDER BY n_distinct ASC, n DESC LIMIT 30;

-- [6] 메타 키 결측. 전체 문서 대비 그 키를 가진 문서 비율
SELECT k, docs, (SELECT count(*) FROM doc WHERE load_ok) AS total,
       round(docs * 100.0 / (SELECT count(*) FROM doc WHERE load_ok), 1) AS have_pct
FROM (
  SELECT trim(regexp_extract(line, '^([^:]+):', 1)) AS k, count(DISTINCT doc_id) AS docs
  FROM (SELECT doc_id, unnest(str_split(fm_raw, chr(10))) AS line
        FROM doc WHERE fm_raw IS NOT NULL)
  WHERE regexp_matches(line, '^[^\s:#-][^:]{0,40}:')
  GROUP BY 1
) ORDER BY docs DESC LIMIT 30;

-- [7] 코퍼스가 아닌 파일. README·LICENSE·색인이 섞여 분모를 1씩 틀리게 만든다.
--     다수와 깊이가 다르거나, 다수가 가진 frontmatter 가 없는 파일을 신고한다
WITH m AS (
  SELECT mode(depth) AS modal_depth,
         count(*) FILTER (WHERE fm_raw IS NOT NULL) * 1.0 / count(*) AS fm_rate
  FROM doc WHERE load_ok
)
SELECT rel_path, depth, sibling_n, n_chars,
       CASE WHEN depth <> (SELECT modal_depth FROM m) THEN '깊이 다름 ' ELSE '' END ||
       CASE WHEN fm_raw IS NULL AND (SELECT fm_rate FROM m) > 0.8
            THEN 'frontmatter 없음' ELSE '' END AS why
FROM doc
WHERE load_ok
  AND (depth <> (SELECT modal_depth FROM m)
       OR (fm_raw IS NULL AND (SELECT fm_rate FROM m) > 0.8))
ORDER BY n_chars DESC LIMIT 15;

-- [8] 마커 표기 변종. 공백만 다른 같은 마커를 찾는다.
--     정규식을 그대로 쓰면 한쪽만 잡혀 측정이 조용히 틀린다
WITH tok AS (
  SELECT unnest(regexp_extract_all(
           body, '[\[\(【〔（]{1}[^\]\)】〕）' || chr(10) || ']{1,16}[\]\)】〕）]{1}')) AS t
  FROM doc WHERE load_ok
)
SELECT replace(replace(t, ' ', ''), chr(9), '') AS normalized,
       count(DISTINCT t) AS variants,
       count(*) AS n,
       string_agg(DISTINCT t, ' | ') AS forms
FROM tok GROUP BY 1 HAVING variants > 1 ORDER BY n DESC LIMIT 20;

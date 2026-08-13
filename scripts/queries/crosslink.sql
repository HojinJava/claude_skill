-- 4단계 · Q7 코퍼스가 둘 이상이면 어떻게 연결되는가. `q.py --write` 가 필요하다.
--
-- 절차는 도메인과 무관하다. 규칙은 하나다:
--   정규식으로 "이름처럼 생긴 것"을 만들어내지 않는다.
--   상대 코퍼스에서 실재 이름 목록을 먼저 만들고, 거기 있는 것만 링크로 인정한다.
-- 도메인에 걸리는 부분은 아래 [설정] 블록에 모았다. 정규식과 컬럼명만 바꿔 넣으면 된다.
--
-- 중간 테이블: xl_cfg(설정) · xl_name(이름+식별자) · xl_name_only(이름) · xl_ref(참조)
--              · xl_named(직접 일치) · xl_alias(약칭 사전)
-- 최종 테이블: xl_link(direct_name · alias_name · carried_name · link_name)
--
-- 1차 링크율이 낮아도 기각하기 전에 [4] 의 실패 표본을 읽는다.
-- 실제 사례에서 원인이 표기 관행으로 갈렸고 47.6% 가 73.3% 가 됐다.

-- [설정 1] 상대 코퍼스. 별도 DB 면 ATTACH 하고, 같은 DB 안에 있으면 이 줄을 지운다
ATTACH IF NOT EXISTS 'out/other.duckdb' AS other (READ_ONLY);

-- [설정 2] 정규식 · 길이 한도. 여기만 바꾸면 다른 도메인에 그대로 쓴다.
--   ref_re    참조 문자열을 통째로 뽑는다. 이름이 붙을 자리까지 앞으로 넉넉히 잡는다.
--             앞부분 수량자는 반드시 게으르게(`{0,70}?`) 둔다. 탐욕적이면 한 매치가
--             연속된 참조 여러 건을 통째로 삼켜 뒤쪽 참조가 조용히 사라진다.
--             제외 문자에 구분자를 더 넣을수록 앞부분이 짧아진다
--   id_re     그 안의 하위 식별자. 캡처 그룹 1개, 숫자여야 한다
--   tail_re   식별자와 그 뒤 꼬리. 이름만 남기려고 지운다
--   paren_re  이름이 아닌 삽입구 (한국 법령 예: 괄호 안 개정 이력)
--   strip_re  이름에 붙는 인용 기호 (한국 법령 예: 「」)
--   name_chars     이름을 이루는 문자 (문자 클래스 본문)
--   prefix_drop_re 이름 앞 수식어 (한국 법령 예: 옛 법을 뜻하는 `구`)
--   anaphor_re     앞 참조를 가리키는 말 (한국 법령 예: `같은 법` · `동법시행령`)
--   name_min/max   이름 후보로 잘라볼 꼬리 길이 범위
CREATE OR REPLACE TABLE xl_cfg AS
SELECT *, '^.*?(' || prefix_drop_re || ')?([' || name_chars || ']+)$' AS lead_re
FROM (SELECT
        '[^,;/' || chr(10) || ']{0,70}?제[0-9]+조' AS ref_re,
        '제([0-9]+)조'                             AS id_re,
        '제[0-9]+조.*$'                            AS tail_re,
        '\([^)]*\)'                                AS paren_re,
        '[「」]'                                    AS strip_re,
        '가-힣A-Za-z0-9ㆍ·'                         AS name_chars,
        '구'                                        AS prefix_drop_re,
        '^(현행|같은법|같은법시행령|같은법시행규칙|동법|동법시행령|동시행령)$' AS anaphor_re,
        2  AS name_min,
        28 AS name_max
     ) c;

-- [설정 3] 참조가 실린 원문. 기본은 본문 전체다.
--   참조가 특정 구간에만 나오면 그 구간만 담은 뷰로 바꾼다. 스캔도 줄고 오탐도 준다
CREATE OR REPLACE VIEW xl_src AS
SELECT doc_id, body AS text FROM doc WHERE load_ok;

-- [설정 4] 실재 이름 집합 (이름, 하위 식별자). 링크 판정의 유일한 근거다.
--   상대 코퍼스가 실제로 갖고 있는 것만 넣는다. 표기가 여러 벌이면 UNION ALL 로 다 넣는다.
--   한국 법령 예: 이름 = 폴더명(공백 제거) 또는 frontmatter 제목 · 식별자 = 조 번호
CREATE OR REPLACE TABLE xl_name AS
SELECT DISTINCT nm, id FROM (
    SELECT replace(d.dir, ' ', '') AS nm,
           try_cast(regexp_extract(t.raw, (SELECT id_re FROM xl_cfg), 1) AS BIGINT) AS id
    FROM other.tok t JOIN other.doc d USING (doc_id)
    UNION ALL
    SELECT replace(trim(regexp_extract(d.fm_raw, '(?m)^제목: *([^' || chr(10) || ']*)', 1)), ' ', ''),
           try_cast(regexp_extract(t.raw, (SELECT id_re FROM xl_cfg), 1) AS BIGINT)
    FROM other.tok t JOIN other.doc d USING (doc_id)
) WHERE nm <> '' AND id IS NOT NULL;

-- 이름만 따로. 식별자 대조 전에 이름 성립 여부부터 본다
CREATE OR REPLACE TABLE xl_name_only AS SELECT DISTINCT nm FROM xl_name;

-- [1] 상대 코퍼스 규모. 이름과 식별자의 분모다. 여기가 비면 아래가 전부 0이 된다
SELECT (SELECT count(*) FROM xl_name_only) AS 실재_이름수,
       (SELECT count(*) FROM xl_name) AS "이름+식별자_쌍",
       (SELECT count(DISTINCT id) FROM xl_name) AS 식별자_종류;

-- [2] 참조 추출. 문서 내 순번을 같이 붙인다.
--     앞 참조를 상속하려면 순서가 필요하고, 순서 없이 뽑으면 보정 자체가 불가능하다
CREATE OR REPLACE TABLE xl_ref AS
WITH raw AS (
    SELECT s.doc_id, regexp_extract_all(s.text, (SELECT ref_re FROM xl_cfg)) AS arr
    FROM xl_src s
), num AS (
    SELECT doc_id, i AS ord, arr[i] AS s FROM raw, range(1, len(arr) + 1) t(i)
), n AS (
    SELECT doc_id, ord, s,
           try_cast(regexp_extract(s, (SELECT id_re FROM xl_cfg), 1) AS BIGINT) AS id,
           regexp_replace(
             replace(replace(
               regexp_replace(
                 regexp_replace(
                   regexp_replace(s, (SELECT tail_re FROM xl_cfg), ''),
                   (SELECT paren_re FROM xl_cfg), '', 'g'),
                 (SELECT strip_re FROM xl_cfg), '', 'g'),
               ' ', ''), chr(9), ''),
             (SELECT lead_re FROM xl_cfg), '\2') AS lead0
    FROM num
)
SELECT doc_id, ord, s, id, lead0 AS lead,
       lead0 = '' AS is_bare,                                          -- C2 열거 생략
       regexp_matches(lead0, (SELECT anaphor_re FROM xl_cfg)) AS is_anaphor  -- C1 조응 참조
FROM n WHERE id IS NOT NULL;

-- [3] 직접 일치. lead 의 꼬리 부분 문자열을 실재 이름과 맞춘다.
--     가장 긴 일치를 채택한다. 짧은 이름이 긴 이름의 꼬리에 걸리는 것을 막는다
CREATE OR REPLACE TABLE xl_named AS
SELECT c.*,
       (SELECT nm FROM (
          SELECT substr(c.lead, length(c.lead) - k + 1, k) AS nm
          FROM range(2, 29) t(k) WHERE length(c.lead) >= k
        ) x WHERE x.nm IN (SELECT nm FROM xl_name_only)
        ORDER BY length(x.nm) DESC LIMIT 1) AS direct_name
FROM xl_ref c;

-- [3] 보정 전 결과. 이름이 실재하는가, 그 이름에 그 식별자가 실재하는가
SELECT count(*) AS 참조,
       count(direct_name) AS 이름_성립,
       round(count(direct_name) * 100.0 / nullif(count(*), 0), 1) AS 이름_pct,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM xl_name l WHERE l.nm = n.direct_name AND l.id = n.id)) AS 링크_성립,
       round(count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM xl_name l WHERE l.nm = n.direct_name AND l.id = n.id)) * 100.0
             / nullif(count(*), 0), 1) AS 링크율_pct
FROM xl_named n;

-- [4] 기각 전에 실패 표본을 읽는다. 표기 관행이면 보정할 수 있고, 상대 코퍼스에
--     그 문서가 없는 것이면 구조적 한계다. 둘을 안 가르면 멀쩡한 가설을 버린다
SELECT lead, count(*) AS n FROM xl_named
WHERE direct_name IS NULL AND lead <> ''
GROUP BY 1 ORDER BY n DESC LIMIT 25;

-- [5] C3 약칭 사전. 실재 이름 중 정확히 하나가 이 말로 끝날 때만 채택한다.
--     둘 이상이면 특정할 수 없다. 추측하지 않는다
CREATE OR REPLACE TABLE xl_alias AS
SELECT lead, real_nm FROM (
    SELECT c.lead,
           (SELECT min(l.nm) FROM xl_name_only l WHERE l.nm LIKE '%' || c.lead) AS real_nm,
           (SELECT count(*) FROM xl_name_only l WHERE l.nm LIKE '%' || c.lead) AS n_match
    FROM (SELECT DISTINCT lead FROM xl_named
          WHERE direct_name IS NULL
            AND length(lead) BETWEEN (SELECT name_min FROM xl_cfg) AND (SELECT name_max FROM xl_cfg)) c
) WHERE n_match = 1;

-- [6] 보정 적용. C1 조응 · C2 열거 생략은 같은 기전이다. 앞 참조의 이름을 상속한다.
--     단계별 컬럼을 남긴다. 어느 규칙이 얼마를 살렸는지 안 보이면 검증이 안 된다
CREATE OR REPLACE TABLE xl_link AS
WITH j AS (
    SELECT n.*, a.real_nm AS alias_name FROM xl_named n LEFT JOIN xl_alias a USING (lead)
), c AS (
    SELECT *, last_value(coalesce(direct_name, alias_name) IGNORE NULLS) OVER (
                  PARTITION BY doc_id ORDER BY ord ROWS UNBOUNDED PRECEDING) AS carried_name
    FROM j
)
SELECT *, CASE WHEN direct_name IS NOT NULL      THEN direct_name
               WHEN alias_name  IS NOT NULL      THEN alias_name
               WHEN is_bare OR is_anaphor        THEN carried_name
               ELSE NULL END AS link_name
FROM c;

-- [7] 보정 전후 분모. 보정은 분자만 늘리지 않는다.
--     이름 없는 참조가 판정 대상으로 들어오면서 분모가 함께 커진다. 둘 다 낸다
SELECT count(*) AS 보정후_분모_참조전체,
       count(*) FILTER (WHERE NOT is_bare AND NOT is_anaphor) AS 보정전_분모_이름있는참조,
       count(*) FILTER (WHERE is_anaphor) AS C1_조응참조,
       count(*) FILTER (WHERE is_bare) AS C2_열거생략
FROM xl_link;

-- [8] 단계별 기여. 규칙 하나를 빼면 몇 건이 죽는지가 여기서 보인다
SELECT count(*) AS 참조,
       count(*) FILTER (WHERE direct_name IS NOT NULL) AS "① 직접 일치",
       count(*) FILTER (WHERE direct_name IS NULL AND alias_name IS NOT NULL) AS "② 약칭 C3",
       count(*) FILTER (WHERE direct_name IS NULL AND alias_name IS NULL
                        AND is_anaphor AND carried_name IS NOT NULL) AS "③ 조응 상속 C1",
       count(*) FILTER (WHERE direct_name IS NULL AND alias_name IS NULL
                        AND NOT is_anaphor AND is_bare AND carried_name IS NOT NULL) AS "④ 열거 상속 C2",
       count(*) FILTER (WHERE link_name IS NULL) AS 미해결
FROM xl_link;

-- [9] 보정 후 링크율. 이름과 식별자가 둘 다 실재해야 링크로 센다
SELECT count(*) AS 참조,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM xl_name l WHERE l.nm = f.link_name AND l.id = f.id)) AS 링크_성립,
       round(count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM xl_name l WHERE l.nm = f.link_name AND l.id = f.id)) * 100.0
             / nullif(count(*), 0), 1) AS 링크율_pct
FROM xl_link f;

-- [10] 집중도 · 참조가 특정 대상에 몰리는가.
--      몰리면 참조 횟수를 중요도 신호로 쓸 수 있고, 인덱싱 우선순위가 생긴다
SELECT link_name, id, count(*) AS n
FROM xl_link f WHERE link_name IS NOT NULL
  AND EXISTS (SELECT 1 FROM xl_name l WHERE l.nm = f.link_name AND l.id = f.id)
GROUP BY 1, 2 ORDER BY n DESC LIMIT 12;

-- [10] 상위 점유율. 상위 1% 대상이 참조의 몇 %를 가져가는가.
--      대상이 100개 미만이면 상위 1%는 1건으로 읽는다(0건이 되어 빈 값이 나오지 않게)
WITH t AS (
    SELECT count(*) AS n FROM xl_link f
    WHERE link_name IS NOT NULL
      AND EXISTS (SELECT 1 FROM xl_name l WHERE l.nm = f.link_name AND l.id = f.id)
    GROUP BY link_name, id
), r AS (SELECT n, row_number() OVER (ORDER BY n DESC) AS rk, count(*) OVER () AS tot FROM t)
SELECT tot AS 참조된_대상수,
       round(sum(n) FILTER (WHERE rk <= greatest(1, tot * 0.01)) * 100.0 / sum(n), 1) AS 상위1pct_점유,
       round(sum(n) FILTER (WHERE rk <= greatest(1, tot * 0.10)) * 100.0 / sum(n), 1) AS 상위10pct_점유
FROM r GROUP BY tot;

-- [11] 도달 범위 · 링크가 하나라도 걸린 문서 비율.
--      링크율이 높아도 몇몇 문서에 몰려 있으면 교차 검색이 대부분의 문서에 안 걸린다
SELECT (SELECT count(*) FROM xl_src) AS 전체_문서,
       count(DISTINCT doc_id) AS 링크보유_문서,
       round(count(DISTINCT doc_id) * 100.0
             / nullif((SELECT count(*) FROM xl_src), 0), 1) AS 도달_pct
FROM xl_link f WHERE link_name IS NOT NULL
  AND EXISTS (SELECT 1 FROM xl_name l WHERE l.nm = f.link_name AND l.id = f.id);

-- [12] 잔여 실패. 보정 후에도 안 되는 것이 구조적 한계인지 확인한다.
--      여기 남은 것을 7단계 미해결로 넘긴다
SELECT lead, count(*) AS n FROM xl_link
WHERE link_name IS NULL AND lead <> '' GROUP BY 1 ORDER BY n DESC LIMIT 15;

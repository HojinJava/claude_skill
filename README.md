# claude_skill

Claude Code 에서 쓰는 개인 스킬 모음.
각 디렉터리가 스킬 하나이고, 진입점은 `<skill-name>/SKILL.md` 다.

## 스킬 목록

| 스킬 | 하는 일 | 언제 부르나 |
|---|---|---|
| [`rag-profiling`](rag-profiling/SKILL.md) | 새 코퍼스에 RAG 를 얹기 전에 문서를 DuckDB 로 먼저 실측하고, 청킹·강화·적재 범위·메타데이터 필터를 기본값이 아니라 근거로 정한다. 산출은 측정 로그가 아니라 **컨설팅 발표물**이다. | "RAG 프로파일링", "이 데이터로 청킹 어떻게", "임베딩 대상 정해야 함", 인덱싱 전 문서 폴더 분석 |
| [`coding-agent-eval-scoring`](coding-agent-eval-scoring/SKILL.md) | 코딩 모델·에이전트를 **PR·브랜치·실제 반영 코드** 기준으로 채점한다. 주관 채점 전에 객관 게이트를 걸고, 지시문의 명령 그대로 빌드·테스트·기동해 확인하며, 같은 프롬프트를 **대조 모델에 블라인드 실행**해 감점이 모델 탓인지 지시문 탓인지 가린다. | "모델 평가", "성적서", "채점 기준", "코딩 모델 비교", "대조군", 벤더 비교·도입 검토 |

## 설치

스킬 디렉터리를 Claude Code 가 읽는 위치에 두면 된다.

```bash
# 사용자 전역
cp -r coding-agent-eval-scoring ~/.claude/skills/

# 특정 프로젝트에만
cp -r coding-agent-eval-scoring <project>/.claude/skills/
```

레포 전체를 클론해서 심볼릭 링크를 걸어도 된다.

```bash
git clone https://github.com/HojinJava/claude_skill.git
ln -s "$PWD/claude_skill/coding-agent-eval-scoring" ~/.claude/skills/coding-agent-eval-scoring
```

## 스킬 추가 규칙

- 디렉터리명 = 스킬명. 소문자·하이픈만 쓴다.
- `SKILL.md` 최상단에 `name` · `description` YAML frontmatter 를 둔다.
  `description` 은 **무엇을 하는지가 아니라 언제 부르는지**를 적고, 한국어 트리거 문구를 포함한다.
- 무거운 참조 자료·실행 스크립트는 `references/` · `scripts/` 로 분리한다.
- 스킬을 추가하면 **이 README 의 스킬 목록 표에 한 줄 추가**한다.

# MARS 공개 레포 설계안

## 분석 요약 — 경쟁 프로젝트

| 프로젝트 | Stars | 핵심 강점 | MARS와 차이 |
|----------|-------|-----------|-------------|
| MetaGPT | 68k | 바이럴 데모 + ICLR 논문 | SW 개발 특화, ML 연구 파이프라인 없음 |
| OpenHands | 71k | Live 데모 + 광범위한 LLM 지원 | 코딩 에이전트, 연구 자동화 아님 |
| GPT-Researcher | 27k | React UI + SSE + 빠른 업데이트 | 웹 리서치 보고서, ML 실험 없음 |
| AI-Scientist | 13.8k | 최초 완전 자동 ML 연구 논문 | HITL 없음, UI 없음, 단일 프레임워크 |
| AgentLaboratory | 5.1k | 완전한 연구 파이프라인 + HITL | 프레임워크 비교 없음, UI 없음 |
| AIDE | 1.3k | ML 벤치마크 최고 성능 | Kaggle 특화, 논문 쓰기 없음 |

---

## MARS의 차별점 (공개용 포지셔닝)

> "CrewAI, AutoGen, LangGraph를 **동일한** ML 연구 파이프라인으로 구현해 비교하는 최초의 시스템.
> AI-Scientist 수준의 자동화 + 스트리밍 React UI + 5단계 Human-in-the-Loop."

경쟁 프로젝트 대비 MARS만 갖는 것:
1. **프레임워크 비교** — 동일 task를 3개 프레임워크로 실행하는 유일한 시스템
2. **풀스택** — Python 파이프라인 + React SSE UI (GPT-Researcher 제외 없음)
3. **엔지니어링 문서화** — 14개 ADR (다른 어느 프로젝트도 이 정도 설계 기록 없음)
4. **구조적 HITL** — 5개 독립 게이트, 각각 전용 UI 컴포넌트와 API 엔드포인트

---

## 레포 구조 (공개 버전)

```
mars/                              ← 레포 이름: "MARS" (Multi-Agent Research System)
│
├── README.md                      ← 완전 재작성 (아래 설계 참고)
├── README_ko.md                   ← 한국어 버전
├── LICENSE                        ← MIT
├── CONTRIBUTING.md                ← 새로 작성
├── CHANGELOG.md                   ← 새로 작성
├── .env.example                   ← 현재 .env에서 키 제거한 버전
├── docker-compose.yml             ← 새로 작성 (진입 장벽 제거)
│
├── mars_crewai/                   ← crewai_prototype/ 이름 변경
├── mars_autogen/                  ← autogen_prototype/ (stub 포함)
├── mars_langgraph/                ← langgraph_prototype/ (stub 포함)
├── mars_ui/                       ← research_system_ui/ 이름 변경
│
├── examples/                      ← 신규: 실행 샘플 출력
│   ├── README.md
│   ├── cifar10_resnet_vs_vit/
│   │   ├── paper.md               ← 생성된 논문
│   │   ├── result.json            ← 실험 결과
│   │   └── events_summary.md      ← 주요 이벤트 요약
│   └── titanic_tabular/
│       └── ...
│
├── benchmarks/                    ← 신규: 프레임워크 비교 결과
│   ├── README.md
│   └── results/
│       └── placeholder.md         ← "Coming soon" (AutoGen/LangGraph 완성 후)
│
├── assets/                        ← 신규: README용 이미지
│   ├── demo.gif                   ← UI 데모 GIF (가장 중요!)
│   ├── architecture.png           ← 아키텍처 다이어그램
│   ├── hitl_flow.png              ← HITL 5개 게이트 플로우
│   └── phase_diagram.png          ← Phase 0-4 파이프라인
│
└── docs/
    ├── ARCHITECTURE.md
    ├── API_SPEC.md
    ├── DEVLOG.md
    ├── PUBLIC_REPO_PLAN.md        ← 이 파일
    ├── decisions/                 ← ADR-001~014
    └── test_checklist_v1.md
```

---

## README 재설계 (섹션 구조)

인기 레포 패턴 분석 결과 — 상위권은 모두 이 구조를 따름:

```
1. 배지 행 (Python/React/License/Status)
2. [데모 GIF] ← 없으면 50% 이탈
3. 한 줄 설명
4. 내비게이션 링크 (Demo · Paper · QuickStart · Benchmark · Docs)
5. Overview — 30초 설명 (input/output/time/control points)
6. Architecture 다이어그램
7. Why MARS? — 경쟁 비교 표
8. Quick Start — 5줄 이내
9. Human-in-the-Loop 설명
10. Benchmark (결과 또는 Coming Soon)
11. Examples (생성된 논문 샘플 링크)
12. Roadmap
13. Documentation (ADR 목록)
14. Citation
15. License
```

### 핵심 변경점 (현재 → 공개 버전)

| 현재 README | 공개 버전 |
|-------------|-----------|
| 데모 없음 | UI 데모 GIF 최상단 |
| `YOUR_USERNAME` placeholder | 실제 GitHub URL |
| 한국어 주석 혼재 | 영어 only (국제 노출용) |
| "Work in progress" 벤치마크 | 현재 가능한 수치 + Coming Soon 분리 |
| ADR 테이블 (과도하게 상세) | 접을 수 있는 `<details>` 블록으로 |
| Quick Start 없음 | Docker 한 줄 + 수동 5줄 |

---

## 공개 전 체크리스트

### 즉시 가능 (1-2일)
- [ ] `.env.example` 생성 (API 키 제거)
- [ ] `CONTRIBUTING.md` 작성
- [ ] `CHANGELOG.md` 작성 (v0.1 → v0.4 히스토리)
- [ ] README 영어 정제 (한국어 제거, placeholder 교체)
- [ ] `examples/` 디렉토리에 샘플 run 출력 추가
- [ ] `README_ko.md` 작성

### 단기 (1주)
- [ ] **UI 데모 GIF 촬영** (가장 임팩트 큼)
- [ ] `docker-compose.yml` 작성
- [ ] 레포 이름/디렉토리 정리 (`crewai_prototype` → `mars_crewai` 등)
- [ ] GitHub Actions CI 추가 (lint/type-check)
- [ ] `.gitignore` 정리 (outputs/, runs/ 제외)

### 중기 (2-4주, 펠로우십 제출 전)
- [ ] arXiv 프리프린트 작성 (MARS 자체에 대한 논문)
- [ ] AutoGen 또는 LangGraph 구현 최소 하나 완성 → 비교 수치 생성
- [ ] Benchmark 섹션에 실제 수치 채우기
- [ ] GitHub Pages or 호스팅 데모

---

## arXiv 논문 구조 제안

제목: **MARS: A Multi-Framework Benchmark for Autonomous ML Research Pipelines**

섹션:
1. Introduction — 왜 프레임워크 비교가 중요한가
2. Related Work — AI-Scientist, AgentLaboratory, AIDE, MetaGPT
3. MARS Pipeline — 5 Phase 아키텍처
4. Human-in-the-Loop Design — 5 게이트 설계
5. Experimental Setup — 5 benchmark tasks × 3 frameworks
6. Results — Task success rate / latency / token usage / repair attempts
7. Analysis — 각 프레임워크의 강/약점
8. Conclusion

이 논문이 나오면 README 최상단에 `[arXiv]` 배지 → 신뢰도 수직 상승

---

## 즉시 실행 가능한 첫 번째 액션

1. **`.env.example` + `CONTRIBUTING.md` 생성** — 30분
2. **`examples/cifar10_resnet_vs_vit/` 디렉토리** 에 기존 run 출력 정리 — 1시간
3. **README 수정** — "YOUR_USERNAME" → 실제 GitHub ID, 한국어 제거 — 30분
4. **GitHub 레포 생성 + push** — 공개 설정
5. **데모 GIF 촬영** — 이게 제일 시간 걸리지만 가장 중요

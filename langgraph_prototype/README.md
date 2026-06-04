# LangGraph 기반 자율 연구 시스템 (Autonomous Research System)

**Workflow 제어 중심 아키텍처 프로토타입 (2순위)**

LangGraph의 StateGraph 위에서 6개 전문 에이전트가 단계적으로 협업하여, 사용자가 제시한 연구 주제에 대해 **계획 수립 → 실험 설계 → 코드 생성 → 실행 → 분석 → 보고서 작성**을 자율적으로 수행하는 시스템입니다.

---

## 핵심 특징

- **범용 연구 시스템**: 특정 연구 주제에 종속되지 않으며, 컴퓨터 비전, NLP, 시계열 예측 등 다양한 분야에 적용 가능
- **에이전트별 LLM 자유 선택**: 각 에이전트마다 서로 다른 LLM 모델 지정 가능 (예: Planner=GPT-5.2, Coder=Claude Sonnet 4.5)
- **자동 디버깅 루프**: 실험 실패 또는 성능 미달 시 자동으로 코드를 수정하고 재실행 (최대 3회)
- **Graceful Degradation**: Pinecone, Docker, W&B 등 외부 서비스 미설정 시 폴백 모드로 자동 전환
- **표준 JSONL 로그**: 통합 UI에서 채팅 형식으로 시각화 가능한 12종 이벤트 로그
- **CLI + REST API**: 터미널 직접 실행과 FastAPI 서버 모드 모두 지원

---

## 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    StateGraph (LangGraph)                     │
│                                                               │
│  START → [Planner] → [Designer] → [Coder] → [Executor]      │
│                                        ↑          │          │
│                                        │    ┌─────┘          │
│                                        │    ↓                │
│                                   [Coder] ← [Analyzer]      │
│                                   (디버깅)     │              │
│                                              ↓              │
│                                          [Writer] → END     │
└─────────────────────────────────────────────────────────────┘
```

| 에이전트 | 역할 | 기본 LLM |
|---|---|---|
| Research Planner | 연구 계획 수립 + 문헌 검색 | GPT-5.2 |
| Experiment Designer | 가설/방법론/실험 설계 | GPT-5.2 |
| Code Generator | 실험 코드 생성 + 디버깅 수정 | Claude Sonnet 4.5 |
| Experiment Executor | Docker 격리 실행 + W&B 추적 | GPT-5-mini |
| Result Analyzer | 결과 분석 + 목표 달성 판단 | Claude Sonnet 4.5 |
| Paper Writer | 학술 보고서 작성 | GPT-5.2 |

---

## 프로젝트 구조

```
langgraph_prototype/
├── README.md                   # 이 파일
├── main.py                     # CLI + FastAPI 진입점
├── config.yaml                 # 에이전트별 LLM 매핑 설정
├── .env.example                # 환경변수 템플릿
├── requirements.txt            # Python 의존성
│
├── config/                     # 설정 관리
│   ├── settings.py             # 설정 로더 (config.yaml + .env)
│   └── llm_factory.py          # 에이전트별 LLM 클라이언트 팩토리
│
├── graph/                      # StateGraph 정의
│   ├── state.py                # ResearchState TypedDict (핵심 상태 객체)
│   ├── research_graph.py       # 노드/엣지/조건부 분기 정의
│   └── builder.py              # 의존성 주입 + 그래프 조립
│
├── nodes/                      # 노드 함수 (에이전트 로직)
│   ├── base.py                 # 공통 헬퍼 (LLM 호출, 컨텍스트 생성)
│   ├── planner.py              # Research Planner
│   ├── designer.py             # Experiment Designer
│   ├── coder.py                # Code Generator
│   ├── executor.py             # Experiment Executor
│   ├── analyzer.py             # Result Analyzer
│   └── writer.py               # Paper Writer
│
├── tools/                      # 외부 서비스 도구
│   ├── pinecone_tool.py        # Pinecone 벡터 검색 (RAG)
│   ├── docker_tool.py          # Docker 코드 실행 샌드박스
│   └── wandb_tool.py           # W&B 실험 추적
│
├── tasks/                      # Celery 비동기 태스크
│   ├── celery_app.py           # Celery 앱 설정
│   └── research_tasks.py       # 비동기 연구 태스크
│
├── api/                        # REST API
│   └── server.py               # FastAPI 서버
│
├── utils/                      # 유틸리티
│   └── logger.py               # 표준 JSONL 로거 (12종 이벤트)
│
├── tests/                      # 테스트
│   └── test_debug_loop.py      # 디버깅 루프 시나리오 테스트
│
├── logs/                       # JSONL 로그 저장 (자동 생성)
└── outputs/                    # 실험 결과 저장 (자동 생성)
```

---

## 설치 방법

### 1. 사전 요구 사항

- Python 3.10 이상
- (선택) Docker Desktop — 코드 격리 실행에 필요
- (선택) Redis — Celery 비동기 태스크에 필요

### 2. 프로젝트 클론 및 의존성 설치

```bash
cd langgraph_prototype

# 가상 환경 생성 (권장)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt
```

### 3. 환경 변수 설정

```bash
# .env 파일 생성
cp .env.example .env
```

`.env` 파일을 열어 **사용할 LLM 서비스의 API 키**를 입력합니다:

```env
# 사용할 서비스의 API 키만 입력하면 됩니다
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxx
GOOGLE_API_KEY=AIzaxxxxxxxxxxxxxxxxxxxxxxx

# (선택) 외부 서비스
PINECONE_API_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
WANDB_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> **참고**: Pinecone, Docker, W&B API 키가 없어도 시스템은 **폴백 모드**로 정상 동작합니다.

### 4. 에이전트별 LLM 설정 (선택)

`config.yaml`에서 각 에이전트가 사용할 LLM 모델을 자유롭게 변경할 수 있습니다:

```yaml
llm_config:
  planner:
    provider: "openai"          # openai | anthropic | google
    model: "gpt-5.2"            # 모델명
    temperature: 0.3
  coder:
    provider: "anthropic"
    model: "claude-sonnet-4-5-20250929"
    temperature: 0.2
  # ... 에이전트별로 자유롭게 조합
```

**지원 LLM 조합 예시:**

| Provider | 모델 | 추천 용도 |
|---|---|---|
| openai | gpt-5.2 | Planner, Designer, Writer |
| openai | gpt-5-mini | Executor (경량 작업) |
| anthropic | claude-sonnet-4-5-20250929 | Coder, Analyzer (코드/분석) |
| anthropic | claude-haiku-4-5-20251001 | 경량 작업 |
| google | gemini-2.5-flash | 빠른 응답 필요 시 |

---

## 실행 방법

### 방법 1: CLI 동기 실행

```bash
# 기본 실행
python main.py run \
  --topic "ResNet과 ViT의 CIFAR-100 성능 비교" \
  --domain "컴퓨터 비전" \
  --target-accuracy 0.85

# 전체 옵션
python main.py run \
  --topic "LSTM vs Transformer 시계열 예측 비교" \
  --domain "시계열 예측" \
  --goal "두 모델의 MAE, RMSE를 비교 분석" \
  --data-path "./data/stock_prices.csv" \
  --output ./outputs \
  --target-accuracy 0.90 \
  --max-experiments 5 \
  --frameworks "PyTorch,scikit-learn"
```

### 방법 2: 대화형 모드

```bash
python main.py interactive
```

시스템이 연구 주제, 분야, 목표 등을 순서대로 질문합니다.

### 방법 3: 드라이런 (LLM 없이 구조 검증)

```bash
python main.py dry-run
```

API 키 없이 그래프 구조와 조건부 엣지가 정상 동작하는지 확인합니다.

### 방법 4: FastAPI 서버

```bash
# 서버 시작
python main.py serve --port 8000

# API 문서 확인
# http://localhost:8000/docs
```

**주요 API 엔드포인트:**

| 엔드포인트 | 메서드 | 설명 |
|---|---|---|
| `/api/v1/health` | GET | 시스템 상태 확인 |
| `/api/v1/config` | GET | 에이전트별 LLM 설정 조회 |
| `/api/v1/config/agents` | PUT | 에이전트별 LLM 동적 변경 |
| `/api/v1/research/run` | POST | 동기 연구 실행 |
| `/api/v1/research/run/async` | POST | Celery 비동기 실행 |
| `/api/v1/research/status/{id}` | GET | 태스크 상태 조회 |
| `/api/v1/research/cancel/{id}` | POST | 태스크 취소 |

**API 호출 예시:**

```bash
curl -X POST http://localhost:8000/api/v1/research/run \
  -H "Content-Type: application/json" \
  -d '{
    "research_topic": "ResNet vs ViT 성능 비교",
    "research_domain": "컴퓨터 비전",
    "target_accuracy": 0.85
  }'
```

### 방법 5: Celery 비동기 실행 (선택)

```bash
# 1. Redis 시작
docker run -d -p 6379:6379 redis:7-alpine

# 2. Celery 워커 시작 (별도 터미널)
celery -A tasks.celery_app worker --loglevel=info --concurrency=2

# 3. FastAPI 서버에서 비동기 실행
curl -X POST http://localhost:8000/api/v1/research/run/async \
  -H "Content-Type: application/json" \
  -d '{"research_topic": "...", "research_domain": "..."}'
```

---

## 디버깅 루프 (핵심 차별점)

이 아키텍처의 핵심 강점은 **자동 디버깅 루프**입니다:

```
Executor → 실행 실패 → Coder (코드 수정) → Executor (재실행)
Analyzer → 성능 미달 → Coder (개선)   → Executor → Analyzer
```

- **실행 실패 루프**: 코드 에러 시 Coder가 에러 메시지를 분석하여 자동 수정
- **성능 개선 루프**: 목표 미달 시 Analyzer의 피드백을 반영하여 코드 개선
- **안전장치**: 최대 3회 루프 후 현재 최선의 결과로 보고서 작성

---

## 로그 형식

모든 활동은 `logs/` 디렉토리에 JSONL 형식으로 기록됩니다:

```json
{"timestamp":"2025-03-02T14:30:00.123Z","session_id":"session_abc123","run_id":"run_def456","event_type":"AGENT_MESSAGE","agent_name":"Research Planner","content":"연구 계획을 수립했습니다.","metadata":{"phase":1}}
```

**지원 이벤트 유형 (12종):**

`SYSTEM_START`, `SYSTEM_END`, `AGENT_THINKING`, `AGENT_MESSAGE`, `TOOL_CALL`, `TOOL_RESULT`, `FILE_CREATED`, `CODE_BLOCK`, `EXPERIMENT_START`, `EXPERIMENT_RESULT`, `USER_QUESTION`, `PHASE_COMPLETE`

---

## 출력 구조

실행 완료 후 `outputs/` 디렉토리에 다음 파일이 생성됩니다:

```
outputs/{run_id}/
├── generated_code/
│   ├── experiment.py           # 에이전트가 생성한 실험 코드
│   └── requirements.txt        # 실험 코드 의존성
├── results/
│   └── metrics.json            # 실험 메트릭 (정확도, 손실 등)
└── report.md                   # 최종 연구 보고서
```

---

## 테스트

```bash
# 디버깅 루프 시나리오 테스트
cd langgraph_prototype
PYTHONPATH=. python -m pytest tests/test_debug_loop.py -v

# 드라이런 (전체 그래프 구조 검증)
python main.py dry-run
```

---

## 트러블슈팅

| 문제 | 해결 방법 |
|---|---|
| `OPENAI_API_KEY not set` | `.env` 파일에 API 키를 설정하세요 |
| Docker 연결 실패 | Docker Desktop이 실행 중인지 확인. 미설치 시 시뮬레이션 모드로 동작 |
| Celery 연결 실패 | Redis가 실행 중인지 확인 (`docker run -d -p 6379:6379 redis:7-alpine`) |
| Pinecone 연결 실패 | API 키 미설정 시 폴백 모드로 자동 전환됨 (정상) |
| W&B 연결 실패 | API 키 미설정 시 로컬 JSON 저장으로 자동 전환됨 (정상) |
| `ModuleNotFoundError` | `pip install -r requirements.txt` 재실행 |

---

## 라이선스

이 프로젝트는 연구 프로토타입으로, 내부 사용 목적으로 개발되었습니다.

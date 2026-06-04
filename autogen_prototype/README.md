# 자율 연구 시스템 (AutoGen 기반 대화형 멀티에이전트 아키텍처)

> **3순위 아키텍처**: 사전에 고정된 워크플로우 없이, 에이전트들이 공유된 그룹 채팅 공간에서 자유롭게 토론하며 모델 설계 및 실험을 자율적으로 수행하는 대화형 멀티에이전트 연구 시스템입니다.

---

## 목차

1. [시스템 개요](#시스템-개요)
2. [아키텍처](#아키텍처)
3. [사전 요구사항](#사전-요구사항)
4. [설치 방법](#설치-방법)
5. [환경 변수 설정](#환경-변수-설정)
6. [설정 파일 (config.yaml)](#설정-파일-configyaml)
7. [실행 방법](#실행-방법)
8. [API 서버 모드](#api-서버-모드)
9. [산출물 구조](#산출물-구조)
10. [로그 형식](#로그-형식)
11. [프로젝트 구조](#프로젝트-구조)
12. [문제 해결](#문제-해결)

---

## 시스템 개요

이 시스템은 **AutoGen 0.4.x**의 `SelectorGroupChat`을 활용하여, 4개의 전문 에이전트가 공유된 채팅 공간에서 자유롭게 토론하며 연구를 수행합니다.

### 핵심 특징

- **범용 설계**: 특정 연구 주제에 종속되지 않으며, 사용자가 주제·목표·데이터를 제공하면 자율적으로 연구를 수행합니다.
- **에이전트별 LLM 매핑**: 각 에이전트에 서로 다른 LLM 모델을 할당할 수 있습니다 (예: Planner→GPT-5.2, Coder→Claude Sonnet 4.5).
- **동적 대화**: 사전 정의된 워크플로우 없이, 대화의 맥락에 따라 다음 발언자가 동적으로 결정됩니다.
- **표준 JSONL 로그**: 모든 대화와 도구 사용이 표준 형식으로 기록되어 통합 UI에서 시각화 가능합니다.

### 에이전트 구성

| 에이전트 | 역할 | 도구 |
|---|---|---|
| **ResearchPlanner** | 연구 전략 수립, 방향 제시 | LanceDB 검색/저장 |
| **Coder** | Python 코드 작성, 실험 구현 | LanceDB 검색 |
| **Critic** | 계획/코드/결과 비판적 검토 | - |
| **Executor** | 코드 실행, 환경 관리 | 코드 실행, 셸 명령 |

---

## 아키텍처

```
사용자 입력 (CLI / API)
        │
        ▼
┌─────────────────────────────────────────────┐
│           ResearchSession (오케스트레이션)      │
│  ┌─────────────────────────────────────────┐ │
│  │       SelectorGroupChat (AutoGen)       │ │
│  │                                         │ │
│  │  ResearchPlanner ←→ Coder              │ │
│  │       ↕              ↕                  │ │
│  │    Critic ←→ Executor                   │ │
│  │                                         │ │
│  │  [커스텀 스피커 선택 로직]                │ │
│  └─────────────────────────────────────────┘ │
│       │              │              │        │
│  ┌────┴────┐  ┌──────┴──────┐  ┌───┴───┐   │
│  │ LanceDB │  │ CodeExecutor│  │ MsgBus│   │
│  │  (RAG)  │  │(OpenHands)  │  │(RMQ)  │   │
│  └─────────┘  └─────────────┘  └───────┘   │
│                      │                       │
│              ┌───────┴───────┐               │
│              │  JSONL Logger │               │
│              └───────────────┘               │
└─────────────────────────────────────────────┘
        │
        ▼
  산출물 (보고서, 코드, 로그)
```

---

## 사전 요구사항

- **Python**: 3.10 이상
- **pip**: 최신 버전
- **LLM API Key**: 최소 1개 이상 (OpenAI, Anthropic, Google 중 선택)

### 선택 사항 (고급 기능)

- **RabbitMQ**: 에이전트 간 비동기 메시지 전달 (미설치 시 인메모리 모드로 동작)
- **OpenHands**: 격리된 코드 실행 환경 (미설치 시 로컬 subprocess로 동작)
- **Docker**: OpenHands 실행에 필요

---

## 설치 방법

### 1. 프로젝트 클론 또는 다운로드

```bash
# 프로젝트 디렉토리로 이동
cd autogen_prototype
```

### 2. 가상환경 생성 (권장)

```bash
python -m venv venv

# Linux/macOS
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 3. 의존성 설치

```bash
# 기본 설치 (필수)
pip install -r requirements.txt

# 임베딩 모델 (LanceDB 검색 기능 사용 시)
pip install sentence-transformers
```

---

## 환경 변수 설정

`.env.example` 파일을 복사하여 `.env` 파일을 생성하고, 사용할 API 키를 입력합니다.

```bash
cp .env.example .env
```

### `.env` 파일 편집

```env
# ===== LLM API Keys =====
# 사용하는 서비스의 API 키만 입력하면 됩니다.

# OpenAI (GPT-5.2, GPT-5-mini 등)
OPENAI_API_KEY=sk-your-openai-api-key-here

# Anthropic (Claude Sonnet 4.5, Claude Opus 4.1 등)
ANTHROPIC_API_KEY=sk-ant-your-anthropic-api-key-here

# Google (Gemini 3 Flash Preview, Gemini 2.5 Pro 등)
GOOGLE_API_KEY=your-google-api-key-here

# ===== 선택 사항 =====
# RabbitMQ (미설정 시 인메모리 모드)
# RABBITMQ_HOST=localhost
# RABBITMQ_PORT=5672

# OpenHands (미설정 시 로컬 실행 모드)
# OPENHANDS_API_URL=http://localhost:3000
```

---

## 설정 파일 (config.yaml)

`config.yaml`에서 **에이전트별 LLM 매핑**을 자유롭게 설정할 수 있습니다.

### 에이전트별 다른 모델 사용 예시

```yaml
agents:
  research_planner:
    llm:
      provider: "openai"
      model: "gpt-5.2"          # 전략적 사고에 강한 모델
  coder:
    llm:
      provider: "anthropic"
      model: "claude-sonnet-4-5-20250929"  # 코드 작성에 강한 모델
  critic:
    llm:
      provider: "openai"
      model: "gpt-5-mini"   # 비용 효율적인 리뷰
  executor:
    llm:
      provider: "openai"
      model: "gpt-5-mini"   # 실행 관리
```

### 지원 프로바이더 및 모델

| 프로바이더 | 환경변수 | 지원 모델 예시 |
|---|---|---|
| `openai` | `OPENAI_API_KEY` | `gpt-5.2`, `gpt-5.2-pro`, `gpt-5.2-codex`, `gpt-5-mini`, `gpt-5-nano` |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-5-20250929`, `claude-haiku-4-5-20251001`, `claude-opus-4-1-20250805` |
| `google` | `GOOGLE_API_KEY` | `gemini-3-pro-preview`, `gemini-3-flash-preview`, `gemini-2.5-pro`, `gemini-2.5-flash` |

### 모든 에이전트에 같은 모델 사용

```yaml
agents:
  research_planner:
    llm:
      provider: "openai"
      model: "gpt-5.2"
  coder:
    llm:
      provider: "openai"
      model: "gpt-5.2"
  critic:
    llm:
      provider: "openai"
      model: "gpt-5.2"
  executor:
    llm:
      provider: "openai"
      model: "gpt-5.2"
```

---

## 실행 방법

### 방법 1: CLI 모드 (가장 간단)

```bash
python main.py run \
  --topic "CIFAR-100 이미지 분류 성능 개선" \
  --goal "ResNet-18 대비 Top-1 정확도 2% 이상 향상" \
  --domain "컴퓨터 비전" \
  --data-path "./data/cifar100" \
  --max-experiments 3 \
  --time-limit 60
```

### 방법 2: 대화형 모드

```bash
python main.py interactive
```

터미널에서 연구 주제, 목표, 분야 등을 대화형으로 입력합니다.

### 방법 3: 스트리밍 모드

```bash
python main.py run \
  --topic "시계열 이상 탐지" \
  --goal "F1-Score 0.9 이상 달성" \
  --domain "시계열 분석" \
  --stream
```

에이전트 대화가 실시간으로 터미널에 출력됩니다.

### CLI 전체 옵션

```
python main.py run --help

옵션:
  --topic           연구 주제 (필수)
  --goal            연구 목표 (필수)
  --domain          연구 분야 (필수)
  --data-path       데이터 경로
  --data-desc       데이터 설명
  --frameworks      선호 프레임워크 (쉼표 구분)
  --max-experiments 최대 실험 횟수 (기본: 3)
  --time-limit      시간 제한 분 (기본: 60)
  --output          산출물 경로 (기본: ./outputs)
  --stream          스트리밍 모드
  --config          설정 파일 경로 (기본: config.yaml)
```

---

## API 서버 모드

### 서버 시작

```bash
python main.py serve --host 0.0.0.0 --port 8000
```

### API 문서

서버 시작 후 브라우저에서 확인:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/` | 서버 상태 확인 |
| `GET` | `/health` | 헬스체크 |
| `POST` | `/api/research/start` | 연구 실행 (동기) |
| `POST` | `/api/research/stream` | 연구 실행 (SSE 스트리밍) |
| `GET` | `/api/logs/{run_id}` | 로그 조회 |
| `GET` | `/api/outputs/{run_id}` | 산출물 조회 |

### API 호출 예시 (curl)

```bash
curl -X POST http://localhost:8000/api/research/start \
  -H "Content-Type: application/json" \
  -d '{
    "research_topic": "자연어 처리 감성 분석",
    "research_goal": "BERT 기반 감성 분류 정확도 92% 달성",
    "research_domain": "NLP",
    "max_experiments": 3,
    "time_limit_minutes": 30
  }'
```

---

## 산출물 구조

각 연구 실행마다 `outputs/{run_id}/` 디렉토리에 산출물이 저장됩니다.

```
outputs/
└── run_20250303_143000/
    ├── report.md              # 연구 보고서 (대화 기록 포함)
    ├── generated_code/        # 에이전트가 생성한 코드
    │   ├── experiment_1.py
    │   ├── experiment_2.py
    │   └── main_experiment.py # 최종 실험 코드
    ├── results/               # 실험 결과
    │   └── figures/           # 생성된 그래프
    └── workspace/             # 코드 실행 작업 디렉토리
```

---

## 로그 형식

모든 이벤트는 `logs/{run_id}.jsonl` 파일에 JSONL 형식으로 기록됩니다.

### 로그 항목 예시

```json
{
  "timestamp": "2025-03-03T05:30:00.000Z",
  "session_id": "autogen_session",
  "run_id": "run_20250303_143000",
  "event_type": "AGENT_MESSAGE",
  "agent_name": "ResearchPlanner",
  "content": "[연구 계획] 1단계: 데이터 탐색 ..."
}
```

### 이벤트 유형

| 이벤트 | 설명 |
|---|---|
| `SYSTEM_START` | 시스템 시작 |
| `SYSTEM_END` | 시스템 종료 |
| `AGENT_MESSAGE` | 에이전트 간 대화 메시지 |
| `AGENT_THINKING` | 에이전트 내부 사고 과정 |
| `TOOL_CALL` | 도구 호출 시작 |
| `TOOL_RESULT` | 도구 호출 결과 |
| `CODE_BLOCK` | 생성된 코드 블록 |
| `EXPERIMENT_START` | 실험 시작 |
| `EXPERIMENT_RESULT` | 실험 결과 |

---

## 프로젝트 구조

```
autogen_prototype/
├── main.py                  # 진입점 (CLI + FastAPI)
├── config.yaml              # 에이전트별 LLM 매핑 설정
├── requirements.txt         # Python 의존성
├── .env.example             # 환경변수 예시
├── .env                     # 환경변수 (사용자 생성)
├── .gitignore
│
├── agents/                  # 에이전트 정의
│   ├── __init__.py
│   ├── planner.py           # ResearchPlanner 에이전트
│   ├── coder.py             # Coder 에이전트
│   ├── critic.py            # Critic 에이전트
│   └── executor.py          # Executor 에이전트
│
├── core/                    # 핵심 모듈
│   ├── __init__.py
│   ├── config_loader.py     # 설정 파일 로더
│   ├── llm_factory.py       # LLM 클라이언트 팩토리
│   ├── chat_manager.py      # GroupChat 관리 및 스피커 선택
│   ├── message_bus.py       # RabbitMQ / 인메모리 메시지 버스
│   ├── research_session.py  # 연구 세션 오케스트레이션
│   └── logger.py            # 표준 JSONL 로거
│
├── tools/                   # 도구
│   ├── __init__.py
│   ├── lance_search.py      # LanceDB 벡터 검색
│   └── code_executor.py     # 코드 실행기 (OpenHands/로컬)
│
├── data/                    # 데이터 디렉토리
│   └── lance_db/            # LanceDB 벡터 저장소
│
├── logs/                    # JSONL 로그 파일
├── outputs/                 # 연구 산출물
└── tests/                   # 테스트
    └── __init__.py
```

---

## 문제 해결

### "API 키가 설정되지 않았습니다"

`.env` 파일에 사용하려는 프로바이더의 API 키가 올바르게 입력되었는지 확인하세요.

```bash
# 환경변수 확인
echo $OPENAI_API_KEY
```

### "ModuleNotFoundError"

의존성이 올바르게 설치되었는지 확인하세요.

```bash
pip install -r requirements.txt
```

### "RabbitMQ 연결 실패"

RabbitMQ가 비활성화된 경우 자동으로 인메모리 모드로 전환됩니다. `config.yaml`에서 확인:

```yaml
rabbitmq:
  enabled: false  # RabbitMQ 미사용
```

### "LanceDB 검색 결과 없음"

지식 저장소가 비어있는 경우입니다. 에이전트가 `add_knowledge` 도구를 사용하여 자동으로 지식을 축적합니다.

### 에이전트 대화가 너무 빨리 종료됨

`config.yaml`에서 `max_rounds`를 늘려보세요:

```yaml
group_chat:
  max_rounds: 30  # 기본 20 → 30으로 증가
```

---

## 라이선스

이 프로젝트는 연구 및 교육 목적으로 제작되었습니다.

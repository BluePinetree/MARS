# 자율 연구 시스템 (CrewAI Prototype)

**Autonomous Research System — Production-Grade Architecture**

CrewAI 기반의 멀티에이전트 자율 연구 시스템 프로토타입입니다. 6개의 전문 AI 에이전트가 협업하여 연구 계획 수립부터 실험 실행, 결과 분석, 보고서 작성까지 전체 연구 과정을 자동화합니다.

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [기술 스택](#2-기술-스택)
3. [프로젝트 구조](#3-프로젝트-구조)
4. [설치 방법](#4-설치-방법)
5. [환경 변수 설정](#5-환경-변수-설정)
6. [에이전트별 LLM 설정](#6-에이전트별-llm-설정)
7. [실행 방법](#7-실행-방법)
8. [API 레퍼런스](#8-api-레퍼런스)
9. [로그 형식](#9-로그-형식)
10. [에이전트 구성](#10-에이전트-구성)
11. [도구 설명](#11-도구-설명)
12. [문제 해결](#12-문제-해결)

---

## 1. 시스템 개요

본 시스템은 **역할 기반의 에이전트 팀(Role-Based Agent Crew)**을 구성하여, 인간 연구팀의 협업 방식을 모방합니다. 사용자가 연구 주제와 목표를 입력하면, 6개의 전문 에이전트가 순차적으로 협력하여 연구를 수행합니다.

```
사용자 입력 → Research Planner → Experiment Designer → Code Generator
                                                           ↓
최종 보고서 ← Paper Writer ← Result Analyzer ← Experiment Executor
```

### 핵심 특징

- **범용 설계**: 특정 연구 주제에 종속되지 않는 범용 구조
- **멀티 LLM 지원**: 에이전트별로 서로 다른 LLM 모델 할당 가능 (OpenAI, Anthropic, Google)
- **안전한 코드 실행**: E2B 샌드박스를 통한 격리된 코드 실행 (로컬 폴백 지원)
- **실험 추적**: MLflow를 통한 체계적인 실험 관리 (로컬 폴백 지원)
- **벡터 메모리**: ChromaDB 기반 RAG로 에이전트 간 지식 공유
- **표준 로그**: JSONL 형식의 구조화된 로그 (통합 UI 연동 가능)
- **이중 인터페이스**: CLI + REST API (FastAPI) 동시 지원

---

## 2. 기술 스택

| 기술 요소 | 선택 기술 | 역할 |
|---|---|---|
| 멀티에이전트 프레임워크 | **CrewAI** | 역할 기반 에이전트 오케스트레이션 |
| 분산 처리 엔진 | **Ray** (선택) | 태스크 병렬 처리 |
| 벡터 데이터베이스 | **ChromaDB** | RAG 기반 메모리 시스템 |
| 코드 실행 환경 | **E2B Sandbox** | 격리된 코드 실행 |
| 실험 관리 | **MLflow** | 실험 파라미터/메트릭 추적 |
| API 서버 | **FastAPI** | REST API + SSE 스트리밍 |
| LLM 프로바이더 | **OpenAI / Anthropic / Google** | 멀티 프로바이더 지원 |

---

## 3. 프로젝트 구조

```
crewai_prototype/
├── README.md                    # 이 문서
├── requirements.txt             # Python 의존성 목록
├── main.py                      # 시스템 진입점 (CLI + API)
├── config.yaml                  # 시스템 설정 (LLM 매핑, 도구 설정)
├── .env.example                 # 환경 변수 템플릿
├── crew.py                      # CrewAI 워크플로우 오케스트레이터
│
├── agents/                      # 에이전트 정의
│   ├── __init__.py
│   ├── research_planner.py      # 연구 기획 에이전트
│   ├── experiment_designer.py   # 실험 설계 에이전트
│   ├── code_generator.py        # 코드 생성 에이전트
│   ├── experiment_executor.py   # 실험 실행 에이전트
│   ├── result_analyzer.py       # 결과 분석 에이전트
│   └── paper_writer.py          # 보고서 작성 에이전트
│
├── tasks/                       # 태스크 정의
│   ├── __init__.py
│   └── research_tasks.py        # 6개 연구 태스크 팩토리
│
├── tools/                       # 외부 도구 구현
│   ├── __init__.py
│   ├── chromadb_tool.py         # 벡터 검색/저장 (RAG)
│   ├── e2b_tool.py              # 코드 실행 (E2B + 로컬 폴백)
│   ├── mlflow_tool.py           # 실험 추적 (MLflow + 로컬 폴백)
│   └── file_tool.py             # 파일 읽기/쓰기
│
├── core/                        # 핵심 시스템 모듈
│   ├── __init__.py
│   ├── config.py                # 설정 로더 (Pydantic)
│   ├── llm_factory.py           # 멀티 프로바이더 LLM 팩토리
│   ├── logger.py                # 표준 JSONL 로거
│   └── callbacks.py             # CrewAI 콜백 핸들러
│
├── logs/                        # JSONL 로그 파일
│   └── {run_id}.jsonl
│
└── outputs/                     # 연구 산출물
    └── {run_id}/
        ├── generated_code/      # 생성된 실험 코드
        ├── results/             # 실험 결과 (메트릭, 그래프)
        └── report.md            # 최종 연구 보고서
```

---

## 4. 설치 방법

### 사전 요구사항

- Python 3.10 이상
- pip 또는 uv 패키지 매니저

### 설치 단계

```bash
# 1. 프로젝트 디렉토리로 이동
cd crewai_prototype

# 2. 가상 환경 생성 (권장)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 또는
venv\Scripts\activate     # Windows

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 환경 변수 설정
cp .env.example .env
# .env 파일을 열어 API 키를 입력하세요
```

### 선택적 구성 요소

```bash
# MLflow 서버 실행 (선택 - 없어도 로컬 폴백으로 동작)
mlflow server --host 0.0.0.0 --port 5000

# Ray 클러스터 (선택 - 분산 처리 시)
# config.yaml에서 ray.enabled: true로 설정
```

---

## 5. 환경 변수 설정

`.env.example`을 `.env`로 복사한 후, 사용할 프로바이더의 API 키를 입력합니다.

```bash
cp .env.example .env
```

```env
# --- LLM API Keys ---
# 사용할 프로바이더의 키만 입력하면 됩니다.

# OpenAI (gpt-5.2, gpt-5-mini, gpt-5-nano 등)
OPENAI_API_KEY=sk-...

# Anthropic (claude-sonnet-4-5, claude-opus-4-1 등)
ANTHROPIC_API_KEY=sk-ant-...

# Google (gemini-3-pro-preview, gemini-2.5-flash 등)
GOOGLE_API_KEY=AI...

# --- Tool API Keys ---
# E2B Sandbox (선택 - 없으면 로컬 subprocess로 폴백)
E2B_API_KEY=e2b_...
```

> **참고**: 사용하지 않는 프로바이더의 키는 비워두어도 됩니다. 단, `config.yaml`의 `agent_llm_mapping`에서 해당 프로바이더를 사용하는 에이전트가 있다면 반드시 키를 입력해야 합니다.

---

## 6. 에이전트별 LLM 설정

`config.yaml`의 `agent_llm_mapping` 섹션에서 각 에이전트에 사용할 LLM을 개별적으로 설정할 수 있습니다.

### 예시: 혼합 모델 구성

```yaml
agent_llm_mapping:
  # GPT-5.2로 연구 계획 수립 (창의적 사고 필요)
  research_planner:
    provider: "openai"
    model: "gpt-5.2"
    temperature: 0.7

  # Claude Sonnet 4.5로 실험 설계 (논리적 분석 필요)
  experiment_designer:
    provider: "anthropic"
    model: "claude-sonnet-4-5-20250929"
    temperature: 0.5

  # Claude Sonnet 4.5로 코드 생성 (정확한 코드 생성)
  code_generator:
    provider: "anthropic"
    model: "claude-sonnet-4-5-20250929"
    temperature: 0.3

  # 경량 모델로 실험 실행 관리
  experiment_executor:
    provider: "openai"
    model: "gpt-5-mini"
    temperature: 0.2

  # Gemini로 결과 분석
  result_analyzer:
    provider: "google"
    model: "gemini-2.5-pro"
    temperature: 0.4

  # GPT-5.2로 보고서 작성
  paper_writer:
    provider: "openai"
    model: "gpt-5.2"
    temperature: 0.6
```

### 사용 가능한 프로바이더 및 모델

| 프로바이더 | 환경변수 | 사용 가능 모델 |
|---|---|---|
| `openai` | `OPENAI_API_KEY` | gpt-5.2, gpt-5.2-pro, gpt-5.2-codex, gpt-5-mini, gpt-5-nano |
| `anthropic` | `ANTHROPIC_API_KEY` | claude-sonnet-4-5-20250929, claude-haiku-4-5-20251001, claude-opus-4-1-20250805 |
| `google` | `GOOGLE_API_KEY` | gemini-3-pro-preview, gemini-3-flash-preview, gemini-2.5-pro, gemini-2.5-flash |

---

## 7. 실행 방법

### 방법 1: 대화형 모드 (가장 쉬운 방법)

```bash
python main.py
```

시스템이 대화형으로 연구 정보를 수집합니다:
- 현재 LLM 설정 상태를 표시
- 연구 주제, 목표, 분야 등을 순서대로 질문
- 입력 확인 후 연구 시작

### 방법 2: CLI 파라미터 직접 전달

```bash
python main.py \
  --topic "ResNet과 ViT의 CIFAR-100 성능 비교" \
  --goal "두 모델의 정확도, 학습 속도, 메모리 사용량을 비교 분석" \
  --domain "컴퓨터 비전" \
  --data-path "./data/cifar100" \
  --output-path "./outputs" \
  --max-experiments 3 \
  --frameworks PyTorch
```

### 방법 3: JSON 파일로 입력

```bash
# research_config.json 파일 준비
python main.py --input research_config.json
```

`research_config.json` 예시:

```json
{
  "research_topic": "ResNet과 ViT의 CIFAR-100 성능 비교",
  "research_goal": "두 모델의 정확도, 학습 속도, 메모리 사용량을 비교 분석",
  "research_domain": "컴퓨터 비전",
  "data_path": "./data/cifar100",
  "output_path": "./outputs",
  "constraints": {
    "max_experiments": 3,
    "time_limit_minutes": 60,
    "preferred_frameworks": ["PyTorch"]
  }
}
```

### 방법 4: REST API 서버

```bash
# API 서버 시작
python main.py --mode api --port 8000

# 또는 uvicorn으로 직접 실행
uvicorn main:app --host 0.0.0.0 --port 8000
```

API 문서는 `http://localhost:8000/docs`에서 확인할 수 있습니다.

---

## 8. API 레퍼런스

### 연구 시작

```bash
POST /api/v1/research
Content-Type: application/json

{
  "research_topic": "ResNet과 ViT의 CIFAR-100 성능 비교",
  "research_goal": "두 모델의 정확도를 비교 분석",
  "research_domain": "컴퓨터 비전",
  "output_path": "./outputs"
}
```

### 실행 상태 조회

```bash
GET /api/v1/research/{run_id}/status
```

### 실시간 로그 스트리밍 (SSE)

```bash
GET /api/v1/research/{run_id}/stream
```

### 최종 결과 조회

```bash
GET /api/v1/research/{run_id}/result
```

### 사용 가능한 LLM 프로바이더 조회

```bash
GET /api/v1/providers
```

---

## 9. 로그 형식

모든 로그는 `logs/{run_id}.jsonl` 파일에 JSONL 형식으로 기록됩니다.

### 로그 이벤트 예시

```json
{
  "timestamp": "2026-03-02T14:30:00.123Z",
  "session_id": "crewai_session_001",
  "run_id": "run_20260302_143000",
  "event_type": "AGENT_MESSAGE",
  "agent_name": "Research Planner",
  "content": "연구 계획을 수립했습니다. 총 3단계로 진행하겠습니다...",
  "metadata": {
    "agent_color": {"color": "#1E40AF", "bg": "#DBEAFE"}
  }
}
```

### 이벤트 유형

| event_type | 설명 | UI 표시 |
|---|---|---|
| `SYSTEM_START` | 시스템 시작 | 시스템 알림 배너 |
| `SYSTEM_END` | 시스템 종료 | 상태별 색상 배너 |
| `AGENT_THINKING` | 에이전트 사고 과정 | 회색 접힘 말풍선 |
| `AGENT_MESSAGE` | 에이전트 간 대화 | 색상 구분 말풍선 |
| `TOOL_CALL` | 도구 호출 | 파란색 카드 |
| `TOOL_RESULT` | 도구 결과 | 초록/빨간 카드 |
| `FILE_CREATED` | 파일 생성 | 파일 아이콘 |
| `CODE_BLOCK` | 코드 블록 | 하이라이팅 블록 |
| `EXPERIMENT_START` | 실험 시작 | 진행 표시줄 |
| `EXPERIMENT_RESULT` | 실험 결과 | 결과 테이블 |
| `PHASE_COMPLETE` | 단계 완료 | 체크마크 |

---

## 10. 에이전트 구성

| 에이전트 | 역할 | 주요 도구 |
|---|---|---|
| **Research Planner** | 연구 주제 분석, 실행 계획 수립 | ChromaDB 검색/저장 |
| **Experiment Designer** | 가설 수립, 실험 프로토콜 설계 | ChromaDB 검색/저장 |
| **Code Generator** | 실험 코드 + MLflow 로깅 코드 생성 | ChromaDB 검색, File I/O |
| **Experiment Executor** | E2B 샌드박스에서 코드 실행 | E2B, MLflow, File I/O |
| **Result Analyzer** | 실험 결과 분석 및 시각화 | MLflow 조회, File I/O |
| **Paper Writer** | 최종 연구 보고서 작성 | ChromaDB 검색, File I/O |

---

## 11. 도구 설명

### ChromaDB (벡터 메모리)
- **chromadb_search**: 의미 기반 유사도 검색
- **chromadb_store**: 텍스트 데이터 벡터 저장

### E2B Sandbox (코드 실행)
- **workspace_execute_code**: 현재 워크스페이스/가상환경에서 Python 코드 실행
- **workspace_prepare_file**: 로컬 파일 메타데이터를 준비
- E2B API 키가 없으면 로컬 subprocess로 폴백

### MLflow (실험 추적)
- **mlflow_log_experiment**: 파라미터/메트릭 기록
- **mlflow_query_results**: 실험 결과 조회
- MLflow 서버가 없으면 로컬 JSON 파일로 폴백

### File I/O
- **file_write**: 파일 생성/저장
- **file_read**: 파일 내용 읽기

---

## 12. 문제 해결

### API 키 오류

```
ValueError: 환경변수 'OPENAI_API_KEY'가 설정되지 않았습니다.
```

→ `.env` 파일에 해당 프로바이더의 API 키를 입력하세요.

### ChromaDB 오류

```
chromadb.errors.ChromaError: ...
```

→ `data/chromadb` 디렉토리를 삭제하고 다시 실행하세요:
```bash
rm -rf data/chromadb
```

### E2B 연결 실패

E2B API 키가 없거나 네트워크 문제가 있으면 자동으로 로컬 subprocess 모드로 전환됩니다. 로그에 `(로컬 폴백 모드)`가 표시됩니다.

### MLflow 서버 연결 실패

MLflow 서버가 실행되지 않으면 자동으로 로컬 JSON 파일(`logs/mlflow_fallback/`)에 기록됩니다.

### 모듈 임포트 오류

```bash
# 프로젝트 루트에서 실행하세요
cd crewai_prototype
python main.py
```

---

## 라이선스

이 프로젝트는 연구 및 교육 목적으로 개발되었습니다.

---

## Quick Start (Integrated UI, 5-Min Setup)

This is the recommended run order for integrated development.

### Fixed Ports (Recommended)

- API: `8000` (crewai_prototype)
- UI: `3000` (research_system_ui)

### 1) Start API First (Terminal A)

```bash
cd crewai_prototype
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
python main.py --mode api --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/api/v1/contract
```

### 2) Start UI Next (Terminal B)

```bash
cd research_system_ui
pnpm install
pnpm dev:3000
```

Open:

- `http://localhost:3000`

### 3) Validate End-to-End Flow

1. Open Dashboard in UI.
2. Click `새 연구 시작` and submit form.
3. Confirm auto-navigation to Session View.
4. Confirm live logs append in real time.
5. Confirm status changes on `STREAM_END`.

### Notes

- If API runs on another host/port, set `research_system_ui/.env.local`:

```env
VITE_API_BASE_URL=http://localhost:8000
```

- Keep API running before launching UI for fastest startup.

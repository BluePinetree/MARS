# 자율 연구 시스템 통합 UI (Autonomous Research System Unified UI)

> 3개의 자율 연구 시스템 프로토타입(CrewAI, LangGraph, AutoGen)의 동작 과정을 하나의 통합된 인터페이스에서 관리하고 시각화하는 웹 애플리케이션입니다.

## 개요

본 프로젝트는 자율 연구 시스템이 생성하는 JSONL 형식의 표준 로그 파일을 읽어, 채팅 형식의 UI에서 에이전트 대화, 코드 실행 결과, 실험 진행 상황 등을 시각화합니다.

### 주요 기능

| 기능 | 설명 |
|------|------|
| **대시보드 뷰** | 모든 연구 세션을 카드로 나열, 아키텍처/상태/진행률 표시 |
| **3-Column 로그 뷰** | 사이드바(세션+필터) + 중앙(채팅형 로그) + 상세 패널 |
| **이벤트별 UI 컴포넌트** | 에이전트 말풍선, 코드 하이라이터, 실험 결과 카드, 도구 호출 카드 등 |
| **로그 필터링** | 에이전트별, 이벤트 유형별 체크박스 필터 |
| **키워드 검색** | 검색어 입력 시 해당 키워드가 포함된 로그만 필터링 |
| **스트리밍 시뮬레이션** | 로그를 실시간으로 하나씩 추가하는 시뮬레이션 모드 |
| **결과 비교 뷰** | 완료된 프로토타입의 실험 메트릭을 바 차트/레이더 차트로 비교 |
| **자동 스크롤** | 새 로그 추가 시 자동 스크롤 (사용자가 위로 스크롤하면 일시 정지) |

## 기술 스택

### 프론트엔드
- **React 19** + **TypeScript** + **Vite**
- **TailwindCSS 4** + **shadcn/ui**
- **Recharts** (차트 시각화)
- **react-syntax-highlighter** (코드 하이라이팅)
- **Framer Motion** (애니메이션)
- **Lucide React** (아이콘)

### 백엔드 (독립 실행용)
- **FastAPI** (Python)
- **WebSocket** 실시간 스트리밍
- **uvicorn** ASGI 서버

## 프로젝트 구조

```
research-system-ui/
├── client/                          # 프론트엔드
│   ├── src/
│   │   ├── components/
│   │   │   ├── LogEvents.tsx        # 이벤트별 UI 컴포넌트 (12종)
│   │   │   ├── LogView.tsx          # 중앙 로그 뷰 (스트리밍 시뮬레이션)
│   │   │   ├── Sidebar.tsx          # 왼쪽 사이드바 (세션+필터)
│   │   │   ├── DetailPanel.tsx      # 오른쪽 상세 정보 패널
│   │   │   └── HighlightText.tsx    # 키워드 하이라이트
│   │   ├── pages/
│   │   │   ├── Home.tsx             # 메인 앱 컨트롤러
│   │   │   ├── Dashboard.tsx        # 대시보드 뷰
│   │   │   ├── SessionView.tsx      # 3-Column 세션 뷰
│   │   │   └── ComparisonView.tsx   # 결과 비교 뷰 (Recharts)
│   │   ├── lib/
│   │   │   ├── types.ts             # TypeScript 타입 정의
│   │   │   ├── constants.ts         # 상수, 에이전트 색상, 유틸리티
│   │   │   └── mockData.ts          # 목 데이터 (3개 세션)
│   │   ├── App.tsx                  # 라우터 및 테마 설정
│   │   └── index.css                # Mission Control 테마 CSS
│   └── index.html
├── backend/                         # 백엔드 (독립 실행용)
│   ├── main.py                      # FastAPI 서버
│   └── requirements.txt             # Python 의존성
└── README.md
```

## 실행 방법

### 프론트엔드 (목 데이터 모드)

현재 프론트엔드는 내장된 목 데이터로 동작합니다. 별도의 백엔드 없이 바로 실행할 수 있습니다.

```bash
# 프로젝트 디렉토리로 이동
cd research-system-ui

# 의존성 설치
pnpm install

# 개발 서버 실행
pnpm dev
```

브라우저에서 `http://localhost:3000`으로 접속합니다.

### 백엔드 (실제 로그 모니터링)

실제 JSONL 로그 파일을 모니터링하려면 FastAPI 백엔드를 실행합니다.

```bash
# 백엔드 디렉토리로 이동
cd research-system-ui/backend

# Python 가상환경 생성 (권장)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 서버 실행 (로그 디렉토리 지정)
python main.py --log-dir /path/to/outputs --port 8000
```

### 백엔드 API

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/v1/sessions` | GET | 모든 세션 목록 및 요약 정보 |
| `/api/v1/sessions/{run_id}/logs` | GET | 특정 세션의 전체 로그 |
| `/ws/v1/sessions/{run_id}/stream` | WebSocket | 실시간 로그 스트리밍 |

## 로그 이벤트 유형

| event_type | UI 컴포넌트 | 설명 |
|-----------|------------|------|
| `SYSTEM_START` / `SYSTEM_END` | 시스템 알림 배너 | 시작/종료 상태에 따라 색상 변경 |
| `AGENT_MESSAGE` | 에이전트 말풍선 | 에이전트별 고유 색상 적용 |
| `AGENT_THINKING` | 접이식 블록 | 클릭 시 사고 과정 펼침 |
| `TOOL_CALL` / `TOOL_RESULT` | 도구 카드 | 호출(파랑)/성공(초록)/실패(빨강) |
| `FILE_CREATED` | 파일 링크 | 파일 경로 표시, 클릭 시 상세 |
| `CODE_BLOCK` | 코드 하이라이터 | 신택스 하이라이팅 + 복사 버튼 |
| `EXPERIMENT_START` | 진행률 표시줄 | 애니메이션 진행 바 |
| `EXPERIMENT_RESULT` | 결과 카드 | 메트릭 테이블 표시 |
| `USER_QUESTION` | 질문 박스 | 노란색 강조, 사용자 응답 필요 |
| `PHASE_COMPLETE` | 단계 구분선 | 체크마크 + 단계명 |

## 디자인 테마

**Mission Control** — 우주 관제 센터에서 영감을 받은 다크 모드 기반 디자인

- **배경**: Deep Navy (#0A0E1A)
- **액센트**: Cyan (#00D4FF) — 실시간 데이터, 활성 상태
- **경고**: Amber (#FFB800) — 사용자 입력 필요, 일시 중지
- **성공**: Emerald (#10B981) — 완료, 성공
- **실패**: Coral (#EF4444) — 에러, 실패
- **타이포그래피**: JetBrains Mono (제목/코드) + IBM Plex Sans (본문)

## 라이선스

MIT License

---

## 통합 실행 가이드 (권장 포트 고정)

새 환경에서 5분 내 실행을 위해 아래 순서를 권장합니다.

### 포트 고정

- UI: `3000`
- API: `8000`

### 1) API 먼저 실행 (Terminal A)

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

동작 확인:

```bash
curl http://localhost:8000/api/v1/contract
```

### 2) UI 실행 (Terminal B)

```bash
cd research_system_ui
pnpm install
pnpm dev:3000
```

접속:

- `http://localhost:3000`

### 3) UI에서 단일 플로우 확인

1. Dashboard에서 `새 연구 시작` 클릭
2. 폼 제출
3. SessionView 자동 이동 확인
4. 로그 실시간 append 확인
5. 완료 시 상태 반영 확인

### 환경변수

UI는 `.env.local`의 `VITE_API_BASE_URL`을 사용합니다.

```env
VITE_API_BASE_URL=http://localhost:8000
```

# 연구 시스템 테스트 체크리스트 v1
> **작성**: 전문가 회의록 기반 | **날짜**: 2026-05-28

## 회의 개요

**참석자**
- **[BE] 김백엔드** — 파이프라인, API, 데이터 처리 전문가
- **[FE] 이프론트** — UI/UX, SSE 스트리밍, 컴포넌트 전문가
- **[QA] 박테스트** — 테스트 전략, 엣지케이스, 통합 검증 전문가

**테스트 원칙 (세 전문가 합의)**: 디버깅 방식 — *"작동하는 가장 작은 단위부터, 그게 되면 그 위"*

> **[QA]** L0부터 막히면 아래로 내려가지 않습니다. L0에서 서버가 안 뜨면 L1은 의미없어요. 각 레벨은 이전 레벨이 **완전히 통과**됐을 때만 진행하고, 각 항목은 `✅ Pass` / `❌ Fail` / `⏭️ Skip`으로 기록합니다.
>
> **[FE]** 프론트 단에서도 마찬가지예요. 컴포넌트가 렌더만 돼도 Pass가 아니라 실제 데이터가 흘러야 Pass입니다.
>
> **[BE]** 백엔드는 Swagger(`localhost:8000/docs`)를 적극 활용하세요. curl 없이도 모든 엔드포인트를 직접 호출할 수 있습니다.

---

## 실행 순서 요약

```
L0 (환경) ──[Fail→종료]──▶ L1-A (API 단위)
                            L1-B (UI 단위)  ─ 병렬 진행 가능
                                ↓
                           L2 (SSE 통합)
                                ↓
                    L3: Phase0 → 1 → 2 → 3 → 4
                                ↓
              L4 시나리오: S1 → S4 → S6 → S3 → S10 → 나머지
                                ↓
                          L5 엣지케이스
```

**시나리오 우선순위**: S1(가장 빠름) → S4(테이블 내장) → S6(커스텀 CSV) → S3(커스텀 이미지) → S10(완전 커스텀) → 나머지

---

## Level 0 — 환경 점검 (목표: 5분 이내)

> **[QA]** 여기서 막히면 코드 문제가 아니라 환경 문제입니다.

| # | 항목 | 확인 방법 | Pass 기준 | 결과 |
|---|------|-----------|-----------|------|
| L0-1 | Python 환경 | `python --version` | ≥ 3.10 | |
| L0-2 | 의존성 설치 | `pip list \| grep crewai` | crewai 패키지 존재 | |
| L0-3 | .env / config.yaml | `crewai_prototype/` 하위 확인 | API 키 설정됨 (OPENAI 또는 ANTHROPIC) | |
| L0-4 | 백엔드 서버 기동 | `uvicorn crewai_prototype.api.app:app --port 8000` | "Application startup complete" 출력 | |
| L0-5 | API 기본 응답 | `curl http://localhost:8000/api/v1/sessions` | HTTP 200, `[]` 또는 배열 반환 | |
| L0-6 | Node 환경 | `node --version && npm --version` | Node ≥ 18 | |
| L0-7 | 프론트엔드 의존성 | `cd research_system_ui && npm install` | 오류 없이 완료 | |
| L0-8 | 프론트엔드 기동 | `npm run dev` (client/) | localhost:5173 접근 가능 | |
| L0-9 | FE→BE 연결 | 브라우저 Dashboard 로딩 | "세션 없음" 상태로 UI 렌더 | |
| L0-10 | CORS 없음 | 브라우저 콘솔 확인 | CORS 에러 없음 | |

---

## Level 1-A — API 단위 테스트 (백엔드 독립 검증)

> **[BE]** L0 통과 후 Swagger(`localhost:8000/docs`) 또는 curl로 UI 없이 API를 직접 검증합니다.

### 세션 관리

| # | 항목 | 요청 | Pass 기준 | 결과 |
|---|------|------|-----------|------|
| L1-1 | 세션 목록 조회 | `GET /api/v1/sessions` | HTTP 200, 배열 반환 | |
| L1-2 | 연구 시작 (최소 payload) | `POST /api/v1/research {"topic":"test"}` | HTTP 200, `run_id` 포함 | |
| L1-3 | 상태 조회 | `GET /api/v1/research/{run_id}/status` | HTTP 200, `status` 필드 존재 | |
| L1-4 | 세션 삭제 | `DELETE /api/v1/sessions/{run_id}` | HTTP 200, `{"deleted": true}` | |

### 상호작용 게이트

| # | 항목 | 요청 | Pass 기준 | 결과 |
|---|------|------|-----------|------|
| L1-5 | 승인 상태 조회 | `GET /api/v1/runs/{run_id}/approval_status` | HTTP 200, `awaiting_approval: false` | |
| L1-6 | 가이던스 상태 조회 | `GET /api/v1/runs/{run_id}/guidance_status` | HTTP 200, `awaiting_guidance: false` | |
| L1-7 | 로그 조회 | `GET /api/v1/sessions/{run_id}/logs` | HTTP 200, 이벤트 배열 | |
| L1-8 | 아티팩트 내용 조회 | `GET /api/v1/research/{run_id}/artifacts/content?path=...` | HTTP 200 또는 404 (경로 미존재 시) | |

---

## Level 1-B — UI 단위 테스트 (프론트엔드 독립 검증)

> **[FE]** Storybook이 없으므로 실제 브라우저에서 상태를 직접 조작해서 확인합니다.

| # | 항목 | 확인 방법 | Pass 기준 | 결과 |
|---|------|-----------|-----------|------|
| L1-9 | Dashboard 렌더 | 브라우저 `/` | 세션 목록 + "새 연구 시작" 버튼 | |
| L1-10 | 연구 시작 폼 | "새 연구 시작" 클릭 | 폼 모달 열림, 모든 필드 렌더 | |
| L1-11 | 고급 설정 토글 | 폼 내 "고급 설정" 클릭 | maxExperiments, timeLimitMinutes 등 노출 | |
| L1-12 | dataPath 필드 | 고급 설정 내 | dataPath + dataDescription 입력 가능 | |
| L1-13 | Sidebar 렌더 | 세션 1개 이상 있을 때 | 세션 카드 + 검색 + 에이전트 필터 | |
| L1-14 | LogView 빈 상태 | 로그 없는 세션 선택 | 빈 상태 UI (에러 없음) | |
| L1-15 | DetailPanel 닫힘 | 이벤트 미선택 시 | DetailPanel 숨김 | |
| L1-16 | ApprovalDialog | 더미 approvalPayload 상태 주입 | 계획/파일 탭 + 승인/거부/수정 버튼 | |
| L1-17 | GuidanceDrawer | 더미 guidancePayload 주입 | 440px Sheet, 경로 + 힌트 입력 + 버튼 | |
| L1-18 | PreflightFlow | 더미 preflightPayload 주입 | 전체화면 오버레이 + 60초 카운트다운 | |
| L1-19 | TokenBudgetBar | tokenBudgetPayload 주입 | 진행 바 + 퍼센트 표시 | |
| L1-20 | RunStatusRibbon | running 세션 선택 | run_id + 경과시간 + Phase 표시 | |
| L1-21 | TerminalPane | exec_stdout 이벤트 포함 세션 | "터미널" 탭 표시 + 초록 텍스트 | |
| L1-22 | ContextInjectionInput | running 세션 | 하단 고정 입력창 + Phase 셀렉터 | |
| L1-23 | ProposalSheet | extension_proposals payload 주입 | 바텀 시트 + 제안 목록 + 실행 버튼 | |

---

## Level 2 — SSE 스트리밍 통합

> **[BE]** 실제 연구를 시작해 서버→클라이언트 이벤트 흐름을 검증합니다.
> **[FE]** 브라우저 DevTools → Network → EventStream 필터로 SSE 패킷을 실시간 확인하세요.

**테스트 payload** (빠른 검증용):
```json
{"topic": "1 + 1 = 2인지 Python 코드로 검증하는 단위 실험"}
```

| # | 항목 | 확인 방법 | Pass 기준 | 결과 |
|---|------|-----------|-----------|------|
| L2-1 | SSE 연결 수립 | DevTools EventStream | `event: log` 패킷 수신 시작 | |
| L2-2 | SYSTEM_START 이벤트 | 로그 뷰 | SystemBanner 렌더 | |
| L2-3 | PHASE_START 이벤트 | Phase 스테퍼 | Phase 0 "Workspace" active | |
| L2-4 | RunStatusRibbon 활성화 | 상단 리본 | "실행 중" + 경과 시간 카운팅 | |
| L2-5 | 이벤트 중복 없음 | 로그 뷰 새로고침 후 | 동일 이벤트 미중복 (mergeLogEvents 검증) | |
| L2-6 | SSE end 이벤트 | DevTools EventStream | `event: end` 수신 + EventSource 닫힘 | |
| L2-7 | 세션 상태 업데이트 | Sidebar | running → completed/failed 점 색상 변경 | |
| L2-8 | 재진입 복원 | 실행 중 탭 새로고침 | 기존 로그 복원 + 게이트 상태 복원 | |

---

## Level 3 — Phase별 파이프라인 검증

> **[QA]** Phase N 실패 시 Phase N+1은 진행하지 않습니다.

### Phase 0: 워크스페이스 생성

| # | 항목 | 확인 방법 | Pass 기준 | 결과 |
|---|------|-----------|-----------|------|
| L3-0-1 | 디렉토리 생성 | 파일 시스템 | `outputs/{run_id}/workspace/`, `paper/`, `handoff/`, `logs/` 생성 | |
| L3-0-2 | PHASE_START(0) | 로그 뷰 | Phase 0 이벤트 수신 | |
| L3-0-3 | PHASE_COMPLETE(0) | Phase 스테퍼 | Phase 0 완료 체크 표시 | |

### Phase 1: 기획 + 승인 게이트

> **[BE]** 테스트 시 `RESEARCH_PIPELINE_APPROVAL_TIMEOUT_SECS=60` 환경변수로 timeout을 단축하세요 (기본 3600초).

| # | 항목 | 확인 방법 | Pass 기준 | 결과 |
|---|------|-----------|-----------|------|
| L3-1-1 | Planner 에이전트 | 로그 뷰 | `agent_name: Planner` AGENT_THINKING/MESSAGE 이벤트 | |
| L3-1-2 | Designer 에이전트 | 로그 뷰 | `agent_name: Designer` 이벤트 + 파일 구조 생성 | |
| L3-1-3 | PLAN_AWAITING_APPROVAL | ApprovalDialog | 모달 자동 팝업 + 계획 내용 표시 | |
| L3-1-4 | 계획 승인 | "승인" 클릭 | POST /approve → 모달 닫힘 → Phase 2 진행 | |
| L3-1-5 | 계획 수정 요청 | "수정 요청" + 피드백 입력 | 재기획 라운드 시작 | |
| L3-1-6 | 계획 거부 | "거부" 클릭 | 파이프라인 중단 + 세션 failed | |

### Phase 2: 코딩

| # | 항목 | 확인 방법 | Pass 기준 | 결과 |
|---|------|-----------|-----------|------|
| L3-2-1 | Stage별 파일 생성 | 로그 뷰 FILE_GENERATED | Stage1(config/utils) → Stage2(data/model) → Stage3(entry) 순서 | |
| L3-2-2 | TokenBudgetBar 활성 | 상단 | token_budget_snapshot → 진행 바 표시 | |
| L3-2-3 | 자동 구문 수정 | 로그 뷰 | FILE_SYNTAX_ERROR → 수정 → FILE_FIXED | |
| L3-2-4 | USER_GUIDANCE_NEEDED | GuidanceDrawer | 5회 실패 후 Sheet 팝업 | |
| L3-2-5 | 가이던스: 힌트 제공 | 힌트 입력 + 재시도 | 수정 재시작 | |
| L3-2-6 | 가이던스: 건너뛰기 | "건너뛰기" | 해당 파일 스킵 후 계속 | |
| L3-2-7 | Smoke test 통과 | 로그 SMOKE_TEST_DONE | entry point 구문/임포트 검증 완료 | |
| L3-2-8 | PHASE_COMPLETE(2) | Phase 스테퍼 | Phase 2 완료 + TokenBudgetBar 사라짐 | |

### Phase 3: 실험 실행

| # | 항목 | 확인 방법 | Pass 기준 | 결과 |
|---|------|-----------|-----------|------|
| L3-3-1 | 터미널 탭 자동 전환 | UI | exec_stdout 수신 → "터미널" 탭 활성 | |
| L3-3-2 | stdout 실시간 스트리밍 | TerminalPane | 초록색 텍스트 실시간 출력 | |
| L3-3-3 | 자동 스크롤 | TerminalPane | 새 줄 출력 시 자동 스크롤 | |
| L3-3-4 | 컨텍스트 주입 | ContextInjectionInput | Ctrl+Enter → POST /inject → "전송됨" | |
| L3-3-5 | result.json 생성 | 파일 시스템 | `outputs/{run_id}/results/result.json` + metrics | |
| L3-3-6 | 실행 실패 분석 | 로그 뷰 | Analyzer 에이전트 진단 + 수정 시도 | |
| L3-3-7 | 반복 실패 에스컬레이션 | GuidanceDrawer | MAX_EXEC_REPAIR(3) 초과 → Sheet 팝업 | |
| L3-3-8 | failure_escalation | 로그 뷰 | OOM/Timeout 2회 이상 → FailureAlert 렌더 | |

### Phase 4: 논문 작성

| # | 항목 | 확인 방법 | Pass 기준 | 결과 |
|---|------|-----------|-----------|------|
| L3-4-1 | 섹션 작성 순서 | 로그 SECTION_DRAFT_DONE | Experiments→Intro→Related→Method→Conclusion→References→Abstract | |
| L3-4-2 | 품질 임계값 | 로그 뷰 | 품질 < 0.70 시 자동 재작성 | |
| L3-4-3 | 논문 파일 생성 | 파일 시스템 | `outputs/{run_id}/paper/` 에 .md 파일 존재 | |
| L3-4-4 | Artifact 뷰 | DetailPanel | 이벤트 클릭 → artifact_paths 링크 표시 | |
| L3-4-5 | extension_proposals | ProposalSheet | Phase 4 완료 후 추가 실험 제안 시트 팝업 | |
| L3-4-6 | SYSTEM_END | 로그 뷰 | 세션 completed + 총 경과시간 표시 | |

---

## Level 4 — 전체 E2E 시나리오

> **[QA]** 각 시나리오는 처음부터 끝까지 독립 실행합니다.
> **[BE]** 4가지 프로필(Vision, Tabular, Timeseries, Generic)을 모두 커버해야 합니다.
> **[FE]** 커스텀 데이터셋은 UI의 `dataPath` + `dataDescription` 필드가 핵심입니다.

---

### [S1] 내장 비전 — CIFAR-10 경량 비교 *(가장 빠른 검증, 여기서 시작)*

> **[BE]** data_path를 지정하지 않으면 torchvision이 자동으로 CIFAR-10을 캐시합니다.

```json
{
  "topic": "CIFAR-10에서 ResNet-18 vs MobileNetV2 정확도 및 파라미터 효율 비교",
  "goal": "동일 에폭(10)에서 두 아키텍처의 top-1 accuracy와 모델 크기 비교",
  "domain": "Computer Vision",
  "maxExperiments": 2,
  "timeLimitMinutes": 30,
  "preferredFrameworks": "PyTorch"
}
```

| # | 체크 항목 | Pass 기준 | 결과 |
|---|-----------|-----------|------|
| S1-1 | 프로필 감지 | `VisionClassificationProfile` 선택 (로그 확인) | |
| S1-2 | 데이터 자동 다운로드 | CIFAR-10 torchvision 자동 캐시 | |
| S1-3 | 파일 구조 | `src/data.py`, `models.py`, `train.py`, `evaluate.py` 생성 | |
| S1-4 | 학습 완료 | result.json에 accuracy 값 존재 | |
| S1-5 | 두 모델 비교 | metrics에 ResNet/MobileNet 결과 각각 포함 | |
| S1-6 | 논문 완성 | paper/ 디렉토리에 .md 파일 생성 | |

---

### [S2] 내장 비전 — CIFAR-100 (기준 시나리오)

```json
{
  "topic": "CIFAR-100 분류에서 Vision Transformer(ViT-tiny) vs ResNet-50 성능 비교",
  "goal": "top-1/top-5 accuracy, 수렴 속도, GPU 메모리 사용량 비교",
  "domain": "Computer Vision",
  "maxExperiments": 3,
  "timeLimitMinutes": 60,
  "preferredFrameworks": "PyTorch"
}
```

| # | 체크 항목 | Pass 기준 | 결과 |
|---|-----------|-----------|------|
| S2-1 | 100-class 데이터 로드 | CIFAR-100 자동 다운로드 | |
| S2-2 | ViT 아키텍처 코드 생성 | Transformer 구조 코드 존재 | |
| S2-3 | top-5 accuracy | metrics에 top5_accuracy 키 존재 | |
| S2-4 | 전체 파이프라인 완주 | Phase 0→4 모두 COMPLETE | |

---

### [S3] 커스텀 이미지 폴더

> **[FE]** `dataPath` 필드에 폴더 경로, `dataDescription`에 클래스/수량 정보를 입력합니다.
> **[BE]** `torchvision.datasets.ImageFolder` 형식(`class_name/image.jpg`)을 사용하면 VisionClassification 프로필이 자동 감지됩니다.

**사전 준비** — 아래 구조로 이미지 폴더 준비:
```
{데이터폴더}/
├── class_A/   (이미지 파일들)
├── class_B/   (이미지 파일들)
└── class_C/   (이미지 파일들)
```

**예시 payload**:
```json
{
  "topic": "딥러닝 기반 식물 병해 조기 탐지: EfficientNet vs DenseNet",
  "goal": "3-class 식물 병해 분류 정확도 비교 및 F1-score 측정",
  "domain": "Agricultural AI / Computer Vision",
  "dataPath": "D:/datasets/plant_disease",
  "dataDescription": "ImageFolder 형식, 3 classes: healthy/powdery_mildew/rust, 각 클래스 200장",
  "maxExperiments": 2,
  "timeLimitMinutes": 45
}
```

| # | 체크 항목 | Pass 기준 | 결과 |
|---|-----------|-----------|------|
| S3-1 | dataPath API 전달 | API 요청 body에 data_path 존재 | |
| S3-2 | 커스텀 경로 사용 | 생성된 코드가 data_path를 dataset root로 사용 | |
| S3-3 | 클래스 수 자동 감지 | 폴더 클래스 수에 맞는 분류기 생성 | |
| S3-4 | F1-score 측정 | metrics에 f1 또는 f1_score 존재 | |
| S3-5 | 논문 데이터셋 설명 | paper에 데이터셋 클래스/크기 언급 | |

---

### [S4] 내장 테이블 — Titanic 이진 분류

> **[BE]** URL 형식의 data_path도 처리 가능한지 확인합니다.

```json
{
  "topic": "Titanic 생존자 예측: XGBoost vs LightGBM vs Random Forest 앙상블 비교",
  "goal": "ROC-AUC 및 F1-score 기준 최적 분류 알고리즘 탐색",
  "domain": "Tabular Machine Learning",
  "dataPath": "https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv",
  "dataDescription": "Titanic 승객 데이터 (891행, target: Survived(0/1), features: Pclass/Sex/Age/SibSp/Parch/Fare/Embarked)",
  "maxExperiments": 3,
  "timeLimitMinutes": 20
}
```

| # | 체크 항목 | Pass 기준 | 결과 |
|---|-----------|-----------|------|
| S4-1 | 프로필 감지 | `TabularSupervisedProfile` 선택 | |
| S4-2 | CSV URL 로드 | pd.read_csv(url) 성공 | |
| S4-3 | 전처리 파일 생성 | `src/preprocess.py` 존재 | |
| S4-4 | 3개 모델 비교 | XGBoost, LightGBM, RF 모두 실행 | |
| S4-5 | ROC-AUC 측정 | metrics에 roc_auc 키 존재 | |

---

### [S5] 내장 테이블 — 회귀 (주택 가격)

```json
{
  "topic": "California Housing 가격 예측: 선형 회귀 vs Gradient Boosting",
  "goal": "RMSE/MAE/R² 기준 예측 정확도 비교, 피처 중요도 분석 포함",
  "domain": "Tabular Regression",
  "dataDescription": "sklearn.datasets.fetch_california_housing 내장 데이터셋 사용, target: 주택 중간 가격(만 달러)",
  "maxExperiments": 2,
  "timeLimitMinutes": 15
}
```

| # | 체크 항목 | Pass 기준 | 결과 |
|---|-----------|-----------|------|
| S5-1 | 회귀 task 감지 | RMSE/MSE loss 사용 코드 생성 | |
| S5-2 | sklearn 내장 데이터 | `fetch_california_housing()` 호출 코드 | |
| S5-3 | R² 측정 | metrics에 r2 또는 r_squared 존재 | |
| S5-4 | 피처 중요도 | results에 feature_importance 출력 | |

---

### [S6] 커스텀 CSV — 사용자 제공 분류 데이터 *(핵심 커스텀 테이블 시나리오)*

> **[QA]** target_column이 description에서 Planner에게 전달되어 생성 코드에 반영되는지 핵심 검증 지점입니다.

**사전 준비**: 임의 분류 CSV 파일 준비 (예: 고객 이탈, 의료 진단 등)

```json
{
  "topic": "통신사 고객 이탈(Churn) 예측: XGBoost 특성 선택 최적화",
  "goal": "Precision-Recall 균형을 고려한 이진 분류 임계값 탐색",
  "domain": "Tabular Classification / Business Analytics",
  "dataPath": "C:/Users/yunsu/datasets/telecom_churn.csv",
  "dataDescription": "통신사 고객 이탈 데이터 (7043행, target 컬럼: Churn(Yes/No), features: tenure/MonthlyCharges/TotalCharges 등 19개 컬럼)",
  "maxExperiments": 2,
  "timeLimitMinutes": 20
}
```

| # | 체크 항목 | Pass 기준 | 결과 |
|---|-----------|-----------|------|
| S6-1 | target_column 추론 | 생성 코드에서 'Churn' 컬럼을 target으로 사용 | |
| S6-2 | 절대 경로 사용 | data_path 절대 경로 그대로 코드에 반영 | |
| S6-3 | 범주형 인코딩 | Yes/No → 0/1 또는 LabelEncoder 변환 코드 | |
| S6-4 | Precision-Recall | metrics에 precision, recall 존재 | |

---

### [S7] 내장 시계열 — 항공 승객 예측

```json
{
  "topic": "월별 항공 승객 수 예측: SARIMA vs LSTM vs N-BEATS 비교",
  "goal": "12개월 Horizon 기준 SMAPE 최소화, 계절성 패턴 포착 능력 평가",
  "domain": "Time Series Forecasting",
  "dataDescription": "AirPassengers 데이터셋 (1949-1960, 144개 월별 관측값, statsmodels 또는 직접 다운로드)",
  "maxExperiments": 3,
  "timeLimitMinutes": 30
}
```

| # | 체크 항목 | Pass 기준 | 결과 |
|---|-----------|-----------|------|
| S7-1 | 프로필 감지 | `TimeseriesForecastingProfile` 선택 | |
| S7-2 | 파일 구조 | `src/dataset.py`, `forecast.py`, `backtest.py` 생성 | |
| S7-3 | SMAPE 측정 | metrics에 smape 존재 | |
| S7-4 | 백테스트 | 훈련/검증 분할 기반 평가 | |
| S7-5 | 계절성 처리 | ACF/PACF 또는 STL 분해 코드 존재 | |

---

### [S8] 커스텀 시계열 — 사용자 제공 날짜+수치 CSV

> **[BE]** description에 timestamp_column과 target_column을 명시하면 Planner가 코드에 반드시 반영해야 합니다.

**사전 준비**: 날짜 컬럼 + 수치 컬럼이 있는 CSV 파일 준비

```json
{
  "topic": "서울시 기온 데이터 기반 7일 예측: Prophet vs Temporal Fusion Transformer",
  "goal": "MAE/RMSE 기준 단기 기온 예측 정확도 비교",
  "domain": "Time Series / Meteorology",
  "dataPath": "C:/Users/yunsu/datasets/seoul_temperature.csv",
  "dataDescription": "서울시 일별 평균기온 (2010-2023, 컬럼: date(yyyy-mm-dd), temp_avg(°C)), 결측치 없음, 5113개 행",
  "maxExperiments": 2,
  "timeLimitMinutes": 30
}
```

| # | 체크 항목 | Pass 기준 | 결과 |
|---|-----------|-----------|------|
| S8-1 | 날짜 파싱 | `pd.to_datetime()` 으로 date 컬럼 파싱 | |
| S8-2 | target_column 추론 | temp_avg를 예측 대상으로 사용 | |
| S8-3 | 7일 horizon | `forecast_horizon=7` 설정 코드 | |
| S8-4 | Prophet 사용 | `from prophet import Prophet` 코드 생성 | |
| S8-5 | MAE/RMSE 측정 | metrics에 mae, rmse 존재 | |

---

### [S9] 제네릭 — NLP 텍스트 분류

```json
{
  "topic": "영화 리뷰 감성 분류: BERT-tiny vs DistilBERT 파인튜닝 효율 비교",
  "goal": "SST-2 기준 accuracy 및 추론 속도(latency) 동시 최적화",
  "domain": "NLP / Text Classification",
  "preferredFrameworks": "PyTorch, HuggingFace Transformers",
  "maxExperiments": 2,
  "timeLimitMinutes": 45
}
```

| # | 체크 항목 | Pass 기준 | 결과 |
|---|-----------|-----------|------|
| S9-1 | 프로필 감지 | GenericScriptProfile 또는 Vision fallback | |
| S9-2 | HuggingFace 코드 | `from transformers import ...` 존재 | |
| S9-3 | SST-2 데이터 로드 | `datasets.load_dataset("sst2")` 호출 | |
| S9-4 | latency 측정 | metrics에 inference_time 또는 latency_ms | |

---

### [S10] 완전 커스텀 — 사용자 폴더 + 자유형 연구 *(궁극의 커스텀 시나리오)*

> **[QA]** 이 시나리오가 "사용자가 폴더에 데이터를 위치시키면 연구 목표를 달성"하는 최종 검증입니다.
> **[FE]** `dataPath`에 폴더 경로, `dataDescription`에 파일 구조와 컬럼 정보를 최대한 상세히 기입하는 것이 핵심입니다.

**사전 준비**:
```
C:/Users/yunsu/my_research_data/
├── train.csv   (학습 데이터)
├── test.csv    (테스트 데이터)
└── README.txt  (선택: 데이터 설명)
```

```json
{
  "topic": "내 데이터로 하는 자유 실험: 최적 ML 알고리즘 탐색",
  "goal": "제공된 데이터셋에서 가장 높은 분류 정확도를 내는 알고리즘 찾기",
  "domain": "Machine Learning",
  "dataPath": "C:/Users/yunsu/my_research_data",
  "dataDescription": "train.csv (1000행, 10개 수치형 피처, target 컬럼: label, 값: 0-4의 5-class 분류), test.csv (200행, 동일 피처 구조)",
  "maxExperiments": 3,
  "timeLimitMinutes": 30
}
```

| # | 체크 항목 | Pass 기준 | 결과 |
|---|-----------|-----------|------|
| S10-1 | 폴더 내 파일 인식 | 생성 코드가 train.csv / test.csv 정확히 참조 | |
| S10-2 | target 컬럼 추론 | 'label' 컬럼을 target으로 인식 | |
| S10-3 | 5-class 분류기 | 출력층 5개 노드 또는 multi-class 설정 | |
| S10-4 | 전처리 자동화 | StandardScaler 또는 동등한 정규화 적용 | |
| S10-5 | 결과 비교표 | 3개 알고리즘 결과 비교 생성 | |
| S10-6 | 논문 완성 | paper/에 실험 결과 논문 파일 생성 | |

---

## Level 5 — 엣지케이스 & 복원력 테스트

> **[QA]** 정상 동작 확인 후, 의도적으로 이상 상황을 만들어 시스템 처리 방식을 검증합니다.

| # | 시나리오 | 유발 방법 | Pass 기준 | 결과 |
|---|----------|-----------|-----------|------|
| L5-1 | 빈 topic 제출 | `topic: ""` 로 POST | 422 오류 또는 UI 폼 검증 차단 | |
| L5-2 | 잘못된 dataPath | 존재하지 않는 경로 입력 | Phase 3에서 FileNotFoundError → GuidanceDrawer 팝업 | |
| L5-3 | 실행 timeout | `timeLimitMinutes: 1` + 오래 걸리는 task | EXPERIMENT_TIMEOUT 후 failed 처리 | |
| L5-4 | 실행 중 취소 | `DELETE /api/v1/runs/{run_id}` | 세션 stopped/failed, 이후 API 정상 응답 | |
| L5-5 | Phase 2 max repair 도달 | 잘못된 힌트 반복 제공 | GuidanceDrawer 반복 팝업 → 사용자 결정 대기 | |
| L5-6 | 세션 재진입 | 실행 중 브라우저 새로고침 | 기존 로그 복원 + SSE 재연결 + 게이트 상태 복원 | |
| L5-7 | 동시 다중 세션 | 2개 연구 연속 시작 | 각 세션 독립 스트리밍, 상호 간섭 없음 | |
| L5-8 | 실행 중 세션 삭제 | `DELETE /api/v1/sessions/{run_id}` | 삭제 거부 또는 자동 취소 후 삭제 | |
| L5-9 | 백엔드 재기동 | 실행 중 uvicorn 재시작 | 프론트 SSE 에러 표시 또는 재연결 시도 | |
| L5-10 | 매우 긴 연구 주제 | topic = 500자 문자열 | 처리 완료 또는 명확한 에러 메시지 | |

---

## 결함 보고 양식

```markdown
### Bug Report #{번호}

- **레벨 / 항목**: L3-2-4 (예시)
- **시나리오**: S6 - 커스텀 CSV (해당 시)
- **재현 단계**:
  1. POST /api/v1/research with dataPath: "C:/nonexistent"
  2. Phase 2 완료 후 Phase 3 시작
  3. ...
- **실제 결과**: 에러 로그 없이 세션이 completed 처리됨
- **기대 결과**: FileNotFoundError → GuidanceDrawer 팝업
- **로그 / 스크린샷**: (첨부)
- **우선순위**: Critical / High / Medium / Low
```

---

## 테스트 결과 저장 위치

```
docs/test_results/
├── L0_environment.md
├── L1_unit.md
├── L2_sse.md
├── L3_pipeline.md
└── L4_scenarios/
    ├── S1_cifar10_result.md
    ├── S3_custom_image_result.md
    ├── S6_custom_csv_result.md
    ├── S10_fully_custom_result.md
    └── ...
```

/**
 * 자율 연구 시스템 통합 UI - 목 데이터
 * Design: Mission Control 테마
 */

import type { LogEvent, Session } from './types';

// CrewAI 세션 로그 이벤트
const crewaiLogs: LogEvent[] = [
  {
    timestamp: '2025-03-02T14:30:00.123Z',
    session_id: 'crewai_session_001',
    run_id: 'run_crewai_20250302',
    event_type: 'SYSTEM_START',
    content: 'CrewAI 기반 자율 연구 시스템을 시작합니다. 연구 주제: ResNet과 ViT의 CIFAR-100 성능 비교',
  },
  {
    timestamp: '2025-03-02T14:30:05.456Z',
    session_id: 'crewai_session_001',
    run_id: 'run_crewai_20250302',
    event_type: 'AGENT_THINKING',
    agent_name: 'Research Planner',
    content: '먼저 연구 계획을 세워야겠다. 1단계는 데이터 준비, 2단계는 모델 학습 및 평가 코드 생성, 3단계는 실험 실행 및 결과 분석으로 구성하자. CIFAR-100 데이터셋은 100개의 클래스를 가지며, 각 클래스당 600개의 이미지(500 train + 100 test)로 구성되어 있다.',
  },
  {
    timestamp: '2025-03-02T14:30:06.789Z',
    session_id: 'crewai_session_001',
    run_id: 'run_crewai_20250302',
    event_type: 'AGENT_MESSAGE',
    agent_name: 'Research Planner',
    content: '연구 계획 수립을 완료했습니다. 총 3단계로 진행하며, 첫 단계로 데이터셋 준비를 시작하겠습니다.',
  },
  {
    timestamp: '2025-03-02T14:30:07.123Z',
    session_id: 'crewai_session_001',
    run_id: 'run_crewai_20250302',
    event_type: 'TOOL_CALL',
    agent_name: 'Data Engineer',
    metadata: { tool_name: 'download_cifar100', tool_input: { path: './data/cifar100' } },
  },
  {
    timestamp: '2025-03-02T14:31:10.456Z',
    session_id: 'crewai_session_001',
    run_id: 'run_crewai_20250302',
    event_type: 'TOOL_RESULT',
    agent_name: 'Data Engineer',
    content: 'CIFAR-100 데이터셋 다운로드 및 전처리 완료. 경로: ./data/cifar100',
    metadata: { success: true },
  },
  {
    timestamp: '2025-03-02T14:31:11.789Z',
    session_id: 'crewai_session_001',
    run_id: 'run_crewai_20250302',
    event_type: 'PHASE_COMPLETE',
    content: 'Phase 1: 데이터 준비 완료',
    metadata: { phase_number: 1, phase_name: 'Data Preparation' },
  },
  {
    timestamp: '2025-03-02T14:31:15.123Z',
    session_id: 'crewai_session_001',
    run_id: 'run_crewai_20250302',
    event_type: 'AGENT_MESSAGE',
    agent_name: 'Code Generator',
    content: 'PyTorch를 사용하여 ResNet50과 ViT-B/16 모델의 학습 및 평가 코드를 생성하겠습니다.',
  },
  {
    timestamp: '2025-03-02T14:31:20.456Z',
    session_id: 'crewai_session_001',
    run_id: 'run_crewai_20250302',
    event_type: 'CODE_BLOCK',
    agent_name: 'Code Generator',
    content: `import torch
import torch.nn as nn
import torchvision
import torchvision.transforms as transforms
from torch.utils.data import DataLoader

# 데이터 전처리 파이프라인
transform_train = transforms.Compose([
    transforms.RandomCrop(32, padding=4),
    transforms.RandomHorizontalFlip(),
    transforms.ToTensor(),
    transforms.Normalize((0.5071, 0.4867, 0.4408),
                         (0.2675, 0.2565, 0.2761))
])

# 모델 초기화
model_resnet = torchvision.models.resnet50(pretrained=False, num_classes=100)
model_vit = torchvision.models.vit_b_16(pretrained=False, num_classes=100)

# 학습 설정
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=200)
criterion = nn.CrossEntropyLoss()`,
    metadata: { language: 'python' },
  },
  {
    timestamp: '2025-03-02T14:31:21.789Z',
    session_id: 'crewai_session_001',
    run_id: 'run_crewai_20250302',
    event_type: 'FILE_CREATED',
    agent_name: 'Code Generator',
    metadata: { file_path: './outputs/run_crewai_20250302/generated_code/main_experiment.py' },
  },
  {
    timestamp: '2025-03-02T14:31:25.123Z',
    session_id: 'crewai_session_001',
    run_id: 'run_crewai_20250302',
    event_type: 'EXPERIMENT_START',
    agent_name: 'Experiment Executor',
    metadata: { experiment_id: 'exp_resnet50_1' },
  },
  {
    timestamp: '2025-03-02T15:01:30.456Z',
    session_id: 'crewai_session_001',
    run_id: 'run_crewai_20250302',
    event_type: 'EXPERIMENT_RESULT',
    agent_name: 'Result Analyzer',
    content: 'ResNet50 실험 완료. 200 에포크 학습 후 최종 결과를 분석했습니다.',
    metadata: {
      metrics: { accuracy: 0.7523, training_time_minutes: 30, memory_usage_gb: 4.5, loss: 0.8912 },
      figures: ['./outputs/run_crewai_20250302/results/figures/loss_curve_resnet.png'],
    },
  },
  {
    timestamp: '2025-03-02T15:01:35.789Z',
    session_id: 'crewai_session_001',
    run_id: 'run_crewai_20250302',
    event_type: 'USER_QUESTION',
    content: 'ResNet50의 정확도가 75.23%로 예상보다 낮습니다. 하이퍼파라미터를 조정하여 추가 실험을 진행할까요, 아니면 이 결과로 ViT와의 비교 분석을 진행할까요?',
  },
  {
    timestamp: '2025-03-02T15:02:00.123Z',
    session_id: 'crewai_session_001',
    run_id: 'run_crewai_20250302',
    event_type: 'SYSTEM_END',
    content: '사용자 응답 대기 중...',
    metadata: { status: 'paused' },
  },
];

// LangGraph 세션 로그 이벤트
const langgraphLogs: LogEvent[] = [
  {
    timestamp: '2025-03-02T14:35:00.000Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'SYSTEM_START',
    content: 'LangGraph 기반 자율 연구 시스템을 시작합니다. 연구 주제: ResNet과 ViT의 CIFAR-100 성능 비교',
  },
  {
    timestamp: '2025-03-02T14:35:03.200Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'AGENT_THINKING',
    agent_name: 'Research Planner',
    content: '상태 그래프를 초기화하고 연구 계획 노드를 실행한다. 입력 검증 → 계획 수립 → 코드 생성 → 실험 실행 → 결과 분석 → 보고서 작성 순서로 진행.',
  },
  {
    timestamp: '2025-03-02T14:35:05.500Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'AGENT_MESSAGE',
    agent_name: 'Research Planner',
    content: '연구 상태 그래프를 초기화했습니다. 6개 노드(planner → designer → coder → executor → analyzer → writer)로 구성된 워크플로우를 실행합니다.',
  },
  {
    timestamp: '2025-03-02T14:35:08.100Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'AGENT_MESSAGE',
    agent_name: 'Experiment Designer',
    content: '실험 설계를 완료했습니다. ResNet50과 ViT-B/16을 동일 조건에서 비교하기 위해 학습률, 배치 크기, 에포크 수를 통일합니다.',
  },
  {
    timestamp: '2025-03-02T14:35:12.300Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'TOOL_CALL',
    agent_name: 'Data Engineer',
    metadata: { tool_name: 'prepare_dataset', tool_input: { dataset: 'cifar100', split_ratio: 0.8 } },
  },
  {
    timestamp: '2025-03-02T14:36:00.000Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'TOOL_RESULT',
    agent_name: 'Data Engineer',
    content: '데이터셋 준비 완료. Train: 40,000 / Val: 10,000 / Test: 10,000',
    metadata: { success: true },
  },
  {
    timestamp: '2025-03-02T14:36:01.500Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'PHASE_COMPLETE',
    content: 'Phase 1: 데이터 준비 및 실험 설계 완료',
    metadata: { phase_number: 1, phase_name: 'Data Preparation & Experiment Design' },
  },
  {
    timestamp: '2025-03-02T14:36:05.000Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'CODE_BLOCK',
    agent_name: 'Code Generator',
    content: `import torch
from transformers import ViTForImageClassification, ViTConfig
from torchvision.models import resnet50

class ExperimentRunner:
    def __init__(self, model_name: str, num_classes: int = 100):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        if model_name == 'resnet50':
            self.model = resnet50(num_classes=num_classes).to(self.device)
        elif model_name == 'vit_b_16':
            config = ViTConfig(num_labels=num_classes, image_size=32)
            self.model = ViTForImageClassification(config).to(self.device)
    
    def train_epoch(self, dataloader, optimizer, criterion):
        self.model.train()
        total_loss, correct, total = 0, 0, 0
        for images, labels in dataloader:
            images, labels = images.to(self.device), labels.to(self.device)
            optimizer.zero_grad()
            outputs = self.model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
            _, predicted = outputs.max(1)
            correct += predicted.eq(labels).sum().item()
            total += labels.size(0)
        return total_loss / len(dataloader), correct / total`,
    metadata: { language: 'python' },
  },
  {
    timestamp: '2025-03-02T14:36:10.000Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'FILE_CREATED',
    agent_name: 'Code Generator',
    metadata: { file_path: './outputs/run_langgraph_20250302/generated_code/experiment_runner.py' },
  },
  {
    timestamp: '2025-03-02T14:36:15.000Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'EXPERIMENT_START',
    agent_name: 'Experiment Executor',
    metadata: { experiment_id: 'exp_resnet50_langgraph' },
  },
  {
    timestamp: '2025-03-02T15:06:20.000Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'EXPERIMENT_RESULT',
    agent_name: 'Result Analyzer',
    content: 'ResNet50 실험 완료. LangGraph 상태 그래프를 통한 자동 하이퍼파라미터 튜닝 적용.',
    metadata: {
      metrics: { accuracy: 0.7812, training_time_minutes: 28, memory_usage_gb: 4.2, loss: 0.7654 },
      figures: ['./outputs/run_langgraph_20250302/results/figures/training_curve.png'],
    },
  },
  {
    timestamp: '2025-03-02T15:06:25.000Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'EXPERIMENT_START',
    agent_name: 'Experiment Executor',
    metadata: { experiment_id: 'exp_vit_langgraph' },
  },
  {
    timestamp: '2025-03-02T15:36:30.000Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'EXPERIMENT_RESULT',
    agent_name: 'Result Analyzer',
    content: 'ViT-B/16 실험 완료. Attention 메커니즘이 CIFAR-100의 세밀한 클래스 구분에 효과적.',
    metadata: {
      metrics: { accuracy: 0.8134, training_time_minutes: 45, memory_usage_gb: 6.8, loss: 0.6321 },
    },
  },
  {
    timestamp: '2025-03-02T15:36:35.000Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'PHASE_COMPLETE',
    content: 'Phase 2: 실험 실행 완료',
    metadata: { phase_number: 2, phase_name: 'Experiment Execution' },
  },
  {
    timestamp: '2025-03-02T15:37:00.000Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'AGENT_MESSAGE',
    agent_name: 'Result Analyzer',
    content: '두 모델의 비교 분석 결과: ViT-B/16이 ResNet50 대비 정확도 3.22%p 우위. 단, 학습 시간은 60.7% 더 소요되고 메모리 사용량도 61.9% 더 높음.',
  },
  {
    timestamp: '2025-03-02T15:38:00.000Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'AGENT_MESSAGE',
    agent_name: 'Paper Writer',
    content: '최종 연구 보고서를 작성 중입니다. ResNet50 vs ViT-B/16 비교 분석 결과를 정리하고 있습니다.',
  },
  {
    timestamp: '2025-03-02T15:40:00.000Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'FILE_CREATED',
    agent_name: 'Paper Writer',
    metadata: { file_path: './outputs/run_langgraph_20250302/report.md' },
  },
  {
    timestamp: '2025-03-02T15:40:05.000Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'PHASE_COMPLETE',
    content: 'Phase 3: 결과 분석 및 보고서 작성 완료',
    metadata: { phase_number: 3, phase_name: 'Analysis & Report' },
  },
  {
    timestamp: '2025-03-02T15:40:10.000Z',
    session_id: 'langgraph_session_001',
    run_id: 'run_langgraph_20250302',
    event_type: 'SYSTEM_END',
    content: 'LangGraph 기반 자율 연구 시스템이 성공적으로 완료되었습니다.',
    metadata: { status: 'completed' },
  },
];

// AutoGen 세션 로그 이벤트
const autogenLogs: LogEvent[] = [
  {
    timestamp: '2025-03-02T14:40:00.000Z',
    session_id: 'autogen_session_001',
    run_id: 'run_autogen_20250302',
    event_type: 'SYSTEM_START',
    content: 'AutoGen 기반 자율 연구 시스템을 시작합니다. 연구 주제: ResNet과 ViT의 CIFAR-100 성능 비교',
  },
  {
    timestamp: '2025-03-02T14:40:05.000Z',
    session_id: 'autogen_session_001',
    run_id: 'run_autogen_20250302',
    event_type: 'AGENT_MESSAGE',
    agent_name: 'Research Planner',
    content: '그룹 채팅을 시작합니다. 참여 에이전트: Research Planner, Code Generator, Critic, Experiment Executor, Result Analyzer',
  },
  {
    timestamp: '2025-03-02T14:40:10.000Z',
    session_id: 'autogen_session_001',
    run_id: 'run_autogen_20250302',
    event_type: 'AGENT_THINKING',
    agent_name: 'Critic',
    content: 'ResNet50과 ViT를 비교할 때 공정한 비교를 위해 동일한 데이터 증강, 학습률 스케줄, 배치 크기를 사용해야 한다. 또한 모델 파라미터 수와 FLOPs도 함께 비교해야 의미 있는 결과가 나올 것이다.',
  },
  {
    timestamp: '2025-03-02T14:40:15.000Z',
    session_id: 'autogen_session_001',
    run_id: 'run_autogen_20250302',
    event_type: 'AGENT_MESSAGE',
    agent_name: 'Critic',
    content: '공정한 비교를 위해 다음 조건을 통일해야 합니다: (1) 동일한 데이터 증강 파이프라인, (2) 동일한 학습률 스케줄러, (3) 모델 파라미터 수 및 FLOPs 보고 필수.',
  },
  {
    timestamp: '2025-03-02T14:40:20.000Z',
    session_id: 'autogen_session_001',
    run_id: 'run_autogen_20250302',
    event_type: 'AGENT_MESSAGE',
    agent_name: 'Code Generator',
    content: 'Critic의 제안을 반영하여 실험 코드를 작성하겠습니다. 두 모델 모두 AdamW 옵티마이저와 코사인 어닐링 스케줄러를 사용하겠습니다.',
  },
  {
    timestamp: '2025-03-02T14:40:30.000Z',
    session_id: 'autogen_session_001',
    run_id: 'run_autogen_20250302',
    event_type: 'CODE_BLOCK',
    agent_name: 'Code Generator',
    content: `import torch
import torch.nn as nn
from thop import profile  # FLOPs 계산용

def count_parameters(model):
    """모델 파라미터 수 계산"""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)

def measure_flops(model, input_size=(1, 3, 32, 32)):
    """FLOPs 측정"""
    dummy_input = torch.randn(*input_size)
    flops, params = profile(model, inputs=(dummy_input,))
    return flops, params

# 공정 비교 설정
config = {
    'optimizer': 'AdamW',
    'lr': 1e-3,
    'weight_decay': 0.05,
    'scheduler': 'CosineAnnealingLR',
    'epochs': 200,
    'batch_size': 128,
}`,
    metadata: { language: 'python' },
  },
  {
    timestamp: '2025-03-02T14:40:35.000Z',
    session_id: 'autogen_session_001',
    run_id: 'run_autogen_20250302',
    event_type: 'PHASE_COMPLETE',
    content: 'Phase 1: 실험 설계 및 코드 생성 완료',
    metadata: { phase_number: 1, phase_name: 'Design & Code Generation' },
  },
  {
    timestamp: '2025-03-02T14:40:40.000Z',
    session_id: 'autogen_session_001',
    run_id: 'run_autogen_20250302',
    event_type: 'EXPERIMENT_START',
    agent_name: 'Experiment Executor',
    metadata: { experiment_id: 'exp_autogen_both_models' },
  },
  {
    timestamp: '2025-03-02T15:10:45.000Z',
    session_id: 'autogen_session_001',
    run_id: 'run_autogen_20250302',
    event_type: 'EXPERIMENT_RESULT',
    agent_name: 'Result Analyzer',
    content: 'ResNet50 실험 결과 (AutoGen 그룹 채팅 기반 자동 튜닝 적용)',
    metadata: {
      metrics: { accuracy: 0.7689, training_time_minutes: 32, memory_usage_gb: 4.3, loss: 0.8234, params_M: 23.5, flops_G: 4.1 },
    },
  },
  {
    timestamp: '2025-03-02T15:40:50.000Z',
    session_id: 'autogen_session_001',
    run_id: 'run_autogen_20250302',
    event_type: 'EXPERIMENT_RESULT',
    agent_name: 'Result Analyzer',
    content: 'ViT-B/16 실험 결과 (AutoGen 그룹 채팅 기반 자동 튜닝 적용)',
    metadata: {
      metrics: { accuracy: 0.7956, training_time_minutes: 48, memory_usage_gb: 7.1, loss: 0.6789, params_M: 86.6, flops_G: 17.6 },
    },
  },
  {
    timestamp: '2025-03-02T15:41:00.000Z',
    session_id: 'autogen_session_001',
    run_id: 'run_autogen_20250302',
    event_type: 'AGENT_MESSAGE',
    agent_name: 'Critic',
    content: '결과 검토: ViT가 정확도에서 우위이나, 파라미터 수가 3.7배, FLOPs가 4.3배 높음. 효율성 관점에서는 ResNet50이 우수. 파라미터 효율성(accuracy/params)을 추가 메트릭으로 제안합니다.',
  },
  {
    timestamp: '2025-03-02T15:42:00.000Z',
    session_id: 'autogen_session_001',
    run_id: 'run_autogen_20250302',
    event_type: 'SYSTEM_END',
    content: 'AutoGen 기반 자율 연구 시스템이 성공적으로 완료되었습니다.',
    metadata: { status: 'completed' },
  },
];

// 세션 목록
export const MOCK_SESSIONS: Session[] = [
  {
    run_id: 'run_crewai_20250302',
    session_id: 'crewai_session_001',
    research_topic: 'ResNet과 ViT의 CIFAR-100 성능 비교',
    architecture: 'CrewAI',
    status: 'paused',
    progress: 65,
    start_time: '2025-03-02T14:30:00.123Z',
    total_events: crewaiLogs.length,
    agents: ['Research Planner', 'Data Engineer', 'Code Generator', 'Experiment Executor', 'Result Analyzer'],
  },
  {
    run_id: 'run_langgraph_20250302',
    session_id: 'langgraph_session_001',
    research_topic: 'ResNet과 ViT의 CIFAR-100 성능 비교',
    architecture: 'LangGraph',
    status: 'completed',
    progress: 100,
    start_time: '2025-03-02T14:35:00.000Z',
    end_time: '2025-03-02T15:40:10.000Z',
    total_events: langgraphLogs.length,
    agents: ['Research Planner', 'Experiment Designer', 'Data Engineer', 'Code Generator', 'Experiment Executor', 'Result Analyzer', 'Paper Writer'],
  },
  {
    run_id: 'run_autogen_20250302',
    session_id: 'autogen_session_001',
    research_topic: 'ResNet과 ViT의 CIFAR-100 성능 비교',
    architecture: 'AutoGen',
    status: 'completed',
    progress: 100,
    start_time: '2025-03-02T14:40:00.000Z',
    end_time: '2025-03-02T15:42:00.000Z',
    total_events: autogenLogs.length,
    agents: ['Research Planner', 'Code Generator', 'Critic', 'Experiment Executor', 'Result Analyzer'],
  },
];

// 전체 로그 데이터 맵
export const MOCK_LOGS: Record<string, LogEvent[]> = {
  run_crewai_20250302: crewaiLogs,
  run_langgraph_20250302: langgraphLogs,
  run_autogen_20250302: autogenLogs,
};

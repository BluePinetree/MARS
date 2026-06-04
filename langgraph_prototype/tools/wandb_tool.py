"""
Weights & Biases (W&B) 실험 추적 도구.

실험 메트릭, 하이퍼파라미터, 아티팩트를 W&B에 기록하고 조회합니다.
Executor 노드가 실험 실행 시 W&B에 자동으로 로깅하며,
Analyzer 노드가 상세 메트릭을 조회하는 데 사용됩니다.

주요 기능:
- 실험 Run 생성 및 메트릭 로깅
- Run 정보 및 상세 메트릭 조회
- 프로젝트 내 모든 Run 비교
- 아티팩트 업로드/다운로드
"""

import os
import json
import logging
from typing import Dict, Optional, Any, List

logger = logging.getLogger(__name__)


class WandBTool:
    """
    Weights & Biases 실험 추적 도구.

    W&B API 키가 설정되지 않은 경우 폴백 모드로 동작하여,
    메트릭을 로컬 JSON 파일에 저장합니다.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        project: str = "autonomous-research",
        entity: Optional[str] = None,
        local_log_dir: str = "./logs/wandb_fallback",
    ):
        """
        W&B 도구를 초기화합니다.

        Args:
            api_key: W&B API 키.
            project: W&B 프로젝트 이름.
            entity: W&B 팀/사용자 이름.
            local_log_dir: 폴백 모드에서 로컬 저장 경로.
        """
        self.api_key = api_key or os.getenv("WANDB_API_KEY")
        self.project = project
        self.entity = entity
        self.local_log_dir = local_log_dir

        self._api = None
        self._initialized = False

        # 폴백 모드용 로컬 저장소
        self._local_runs: Dict[str, Dict] = {}

        if self.api_key:
            try:
                self._initialize_wandb()
            except Exception as e:
                logger.warning(f"W&B 초기화 실패 (폴백 모드 사용): {e}")
        else:
            logger.info("W&B API 키 미설정 - 폴백 모드로 동작합니다.")

    def _initialize_wandb(self):
        """W&B API 클라이언트를 초기화합니다."""
        try:
            import wandb

            os.environ["WANDB_API_KEY"] = self.api_key
            self._api = wandb.Api()
            self._initialized = True
            logger.info(f"W&B 연결 완료 (프로젝트: {self.project})")
        except ImportError:
            logger.warning("wandb 패키지가 설치되지 않았습니다.")
        except Exception as e:
            logger.warning(f"W&B 초기화 에러: {e}")

    def create_run(
        self,
        experiment_id: str,
        config: Optional[Dict] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        새 W&B Run을 생성합니다.

        Args:
            experiment_id: 실험 ID (Run 이름으로 사용).
            config: 하이퍼파라미터 설정.
            tags: Run 태그 리스트.

        Returns:
            dict: {"run_id": str, "url": str}
        """
        if self._initialized:
            try:
                import wandb

                run = wandb.init(
                    project=self.project,
                    entity=self.entity,
                    name=experiment_id,
                    config=config or {},
                    tags=tags or [],
                    reinit=True,
                )

                return {
                    "run_id": run.id,
                    "url": run.get_url(),
                    "name": experiment_id,
                }
            except Exception as e:
                logger.error(f"W&B Run 생성 실패: {e}")

        # 폴백: 로컬 저장
        self._local_runs[experiment_id] = {
            "run_id": experiment_id,
            "url": f"(local) {self.local_log_dir}/{experiment_id}",
            "name": experiment_id,
            "config": config or {},
            "metrics": {},
            "tags": tags or [],
        }
        return {
            "run_id": experiment_id,
            "url": f"(local) {self.local_log_dir}/{experiment_id}",
            "name": experiment_id,
        }

    def log_metrics(
        self,
        experiment_id: str,
        metrics: Dict[str, Any],
        step: Optional[int] = None,
    ):
        """
        메트릭을 W&B에 로깅합니다.

        Args:
            experiment_id: 실험 ID.
            metrics: 로깅할 메트릭 딕셔너리.
            step: 학습 스텝 번호.
        """
        if self._initialized:
            try:
                import wandb

                if wandb.run and wandb.run.name == experiment_id:
                    wandb.log(metrics, step=step)
                    return
            except Exception as e:
                logger.warning(f"W&B 메트릭 로깅 실패: {e}")

        # 폴백: 로컬 저장
        if experiment_id in self._local_runs:
            existing = self._local_runs[experiment_id].get("metrics", {})
            existing.update(metrics)
            self._local_runs[experiment_id]["metrics"] = existing
        else:
            self._local_runs[experiment_id] = {"metrics": metrics}

    def finish_run(self, experiment_id: str):
        """W&B Run을 종료합니다."""
        if self._initialized:
            try:
                import wandb

                if wandb.run:
                    wandb.finish()
                    return
            except Exception as e:
                logger.warning(f"W&B Run 종료 실패: {e}")

        # 폴백: 로컬 파일로 저장
        self._save_local_run(experiment_id)

    def get_run_info(self, experiment_id: str) -> Dict[str, Any]:
        """
        Run 정보를 조회합니다.

        Args:
            experiment_id: 실험 ID.

        Returns:
            dict: {"url": str, "metrics": dict, "config": dict, "state": str}
        """
        if self._initialized and self._api:
            try:
                runs = self._api.runs(
                    f"{self.entity}/{self.project}" if self.entity else self.project,
                    filters={"display_name": experiment_id},
                )
                for run in runs:
                    return {
                        "url": run.url,
                        "metrics": dict(run.summary),
                        "config": dict(run.config),
                        "state": run.state,
                    }
            except Exception as e:
                logger.warning(f"W&B Run 조회 실패: {e}")

        # 폴백: 로컬 데이터
        if experiment_id in self._local_runs:
            local = self._local_runs[experiment_id]
            return {
                "url": local.get("url", ""),
                "metrics": local.get("metrics", {}),
                "config": local.get("config", {}),
                "state": "finished",
            }

        return {"url": "", "metrics": {}, "config": {}, "state": "not_found"}

    def get_detailed_metrics(self, experiment_id: str) -> str:
        """
        Run의 상세 메트릭을 포맷된 문자열로 반환합니다.
        Analyzer 노드가 분석에 사용합니다.

        Args:
            experiment_id: 실험 ID.

        Returns:
            str: 포맷된 메트릭 문자열.
        """
        info = self.get_run_info(experiment_id)
        metrics = info.get("metrics", {})
        config = info.get("config", {})

        lines = [f"### 실험: {experiment_id}"]

        if metrics:
            lines.append("\n**메트릭:**")
            for k, v in sorted(metrics.items()):
                if isinstance(v, float):
                    lines.append(f"- {k}: {v:.6f}")
                else:
                    lines.append(f"- {k}: {v}")

        if config:
            lines.append("\n**하이퍼파라미터:**")
            for k, v in sorted(config.items()):
                lines.append(f"- {k}: {v}")

        lines.append(f"\n**상태:** {info.get('state', 'unknown')}")
        lines.append(f"**URL:** {info.get('url', 'N/A')}")

        return "\n".join(lines)

    def compare_runs(
        self,
        experiment_ids: Optional[List[str]] = None,
        metric_keys: Optional[List[str]] = None,
    ) -> str:
        """
        여러 Run의 메트릭을 비교합니다.

        Args:
            experiment_ids: 비교할 실험 ID 리스트. None이면 전체.
            metric_keys: 비교할 메트릭 키 리스트.

        Returns:
            str: 비교 테이블 문자열.
        """
        all_runs = {}

        if self._initialized and self._api:
            try:
                runs = self._api.runs(
                    f"{self.entity}/{self.project}" if self.entity else self.project
                )
                for run in runs:
                    if experiment_ids is None or run.name in experiment_ids:
                        all_runs[run.name] = dict(run.summary)
            except Exception as e:
                logger.warning(f"W&B Run 비교 실패: {e}")

        # 로컬 데이터 병합
        for eid, data in self._local_runs.items():
            if experiment_ids is None or eid in experiment_ids:
                all_runs[eid] = data.get("metrics", {})

        if not all_runs:
            return "(비교할 실험이 없습니다.)"

        # 메트릭 키 결정
        if metric_keys is None:
            metric_keys = set()
            for metrics in all_runs.values():
                metric_keys.update(metrics.keys())
            metric_keys = sorted(metric_keys)

        # 테이블 생성
        header = "| 실험 | " + " | ".join(metric_keys) + " |"
        separator = "|---|" + "|".join(["---"] * len(metric_keys)) + "|"
        rows = []

        for name, metrics in sorted(all_runs.items()):
            values = []
            for key in metric_keys:
                v = metrics.get(key, "N/A")
                if isinstance(v, float):
                    values.append(f"{v:.4f}")
                else:
                    values.append(str(v))
            rows.append(f"| {name} | " + " | ".join(values) + " |")

        return "\n".join([header, separator] + rows)

    def _save_local_run(self, experiment_id: str):
        """폴백 모드에서 Run 데이터를 로컬 파일로 저장합니다."""
        from pathlib import Path

        log_dir = Path(self.local_log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        if experiment_id in self._local_runs:
            run_file = log_dir / f"{experiment_id}.json"
            run_file.write_text(
                json.dumps(self._local_runs[experiment_id], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(f"W&B 폴백: 로컬 저장 완료 → {run_file}")

    @property
    def is_available(self) -> bool:
        """W&B 연결 상태를 반환합니다."""
        return self._initialized

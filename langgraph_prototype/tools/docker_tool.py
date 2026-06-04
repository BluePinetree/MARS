"""
Docker 코드 실행 도구.

LLM이 생성한 실험 코드를 Docker 컨테이너 내에서 안전하게 실행합니다.
Dockerfile을 동적으로 생성하고, 이미지 빌드 → 컨테이너 실행 → 로그 수집 → 정리
전체 라이프사이클을 자동화합니다.

주요 기능:
- 동적 Dockerfile 생성 (의존성 자동 설치)
- 격리된 환경에서 코드 실행
- W&B API 키 등 환경변수 안전 주입
- 실행 로그 및 결과 파일 수집
- 타임아웃 및 리소스 제한
"""

import os
import json
import time
import tempfile
import logging
from pathlib import Path
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


class DockerTool:
    """
    Docker 기반 코드 실행 도구.

    Docker가 설치되지 않은 환경에서는 폴백 모드(로컬 subprocess)로 동작합니다.
    """

    def __init__(
        self,
        base_image: str = "python:3.11-slim",
        memory_limit: str = "4g",
        cpu_limit: float = 2.0,
        timeout_seconds: int = 600,
        network_mode: str = "none",
    ):
        """
        Docker 도구를 초기화합니다.

        Args:
            base_image: 기본 Docker 이미지.
            memory_limit: 메모리 제한.
            cpu_limit: CPU 제한 (코어 수).
            timeout_seconds: 실행 타임아웃 (초).
            network_mode: 네트워크 모드 ("none"=격리, "bridge"=네트워크 허용).
        """
        self.base_image = base_image
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.timeout_seconds = timeout_seconds
        self.network_mode = network_mode

        self._client = None
        self._initialized = False

        try:
            self._initialize_docker()
        except Exception as e:
            logger.warning(f"Docker 초기화 실패 (폴백 모드 사용): {e}")

    def _initialize_docker(self):
        """Docker 클라이언트를 초기화합니다."""
        try:
            import docker

            self._client = docker.from_env()
            # Docker 데몬 연결 확인
            self._client.ping()
            self._initialized = True
            logger.info("Docker 데몬 연결 완료")
        except ImportError:
            logger.warning("docker 패키지가 설치되지 않았습니다.")
        except Exception as e:
            logger.warning(f"Docker 데몬 연결 실패: {e}")

    def execute(
        self,
        code: str,
        requirements: str = "",
        experiment_id: str = "experiment",
        env_vars: Optional[Dict[str, str]] = None,
        extra_files: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        코드를 Docker 컨테이너에서 실행합니다.

        Args:
            code: 실행할 Python 코드.
            requirements: pip 패키지 목록 (줄바꿈 구분).
            experiment_id: 실험 ID.
            env_vars: 컨테이너에 주입할 환경변수.
            extra_files: 추가 파일 {"파일명": "내용"}.

        Returns:
            dict: {
                "success": bool,
                "logs": str,
                "metrics": dict,
                "exit_code": int,
                "duration_seconds": float,
            }
        """
        if self._initialized and self._client:
            return self._execute_docker(code, requirements, experiment_id, env_vars, extra_files)
        else:
            return self._execute_fallback(code, requirements, experiment_id, env_vars)

    def _execute_docker(
        self,
        code: str,
        requirements: str,
        experiment_id: str,
        env_vars: Optional[Dict[str, str]],
        extra_files: Optional[Dict[str, str]],
    ) -> Dict[str, Any]:
        """Docker 컨테이너에서 코드를 실행합니다."""
        import docker

        container = None
        start_time = time.time()

        try:
            # 임시 빌드 디렉토리 생성
            with tempfile.TemporaryDirectory(prefix=f"research_{experiment_id}_") as build_dir:
                build_path = Path(build_dir)

                # 코드 파일 저장
                (build_path / "main_experiment.py").write_text(code, encoding="utf-8")

                # requirements.txt 저장
                if requirements:
                    (build_path / "requirements.txt").write_text(requirements, encoding="utf-8")

                # 추가 파일 저장
                if extra_files:
                    for fname, content in extra_files.items():
                        (build_path / fname).write_text(content, encoding="utf-8")

                # 결과 수집 스크립트 생성
                result_collector = self._generate_result_collector()
                (build_path / "collect_results.py").write_text(result_collector, encoding="utf-8")

                # Dockerfile 생성
                dockerfile_content = self._generate_dockerfile(requirements)
                (build_path / "Dockerfile").write_text(dockerfile_content, encoding="utf-8")

                # Docker 이미지 빌드
                image_tag = f"research-exp-{experiment_id}:latest"
                logger.info(f"Docker 이미지 빌드 시작: {image_tag}")

                image, build_logs = self._client.images.build(
                    path=str(build_path),
                    tag=image_tag,
                    rm=True,
                )

                # 환경변수 구성
                container_env = {"EXPERIMENT_ID": experiment_id}
                if env_vars:
                    container_env.update({k: v for k, v in env_vars.items() if v})

                # W&B 사용 시 네트워크 허용
                net_mode = self.network_mode
                if env_vars and env_vars.get("WANDB_API_KEY"):
                    net_mode = "bridge"

                # 컨테이너 실행
                logger.info(f"Docker 컨테이너 실행: {experiment_id}")
                container = self._client.containers.run(
                    image=image_tag,
                    command="python main_experiment.py",
                    environment=container_env,
                    mem_limit=self.memory_limit,
                    nano_cpus=int(self.cpu_limit * 1e9),
                    network_mode=net_mode,
                    detach=True,
                    remove=False,
                )

                # 실행 완료 대기
                result = container.wait(timeout=self.timeout_seconds)
                exit_code = result.get("StatusCode", -1)

                # 로그 수집
                logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

                # 결과 메트릭 추출
                metrics = self._extract_metrics_from_logs(logs)

                duration = time.time() - start_time
                success = exit_code == 0

                logger.info(
                    f"Docker 실행 완료: exit_code={exit_code}, "
                    f"duration={duration:.1f}s, success={success}"
                )

                return {
                    "success": success,
                    "logs": logs,
                    "metrics": metrics,
                    "exit_code": exit_code,
                    "duration_seconds": round(duration, 2),
                }

        except docker.errors.ContainerError as e:
            duration = time.time() - start_time
            return {
                "success": False,
                "logs": str(e),
                "metrics": {},
                "exit_code": e.exit_status,
                "duration_seconds": round(duration, 2),
            }

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Docker 실행 에러: {e}")
            return {
                "success": False,
                "logs": f"Docker 실행 에러: {str(e)}",
                "metrics": {},
                "exit_code": -1,
                "duration_seconds": round(duration, 2),
            }

        finally:
            # 컨테이너 정리
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

    def _execute_fallback(
        self,
        code: str,
        requirements: str,
        experiment_id: str,
        env_vars: Optional[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        Docker 미사용 시 로컬 subprocess로 코드를 실행합니다.
        보안 격리가 없으므로 프로토타입/테스트 용도로만 사용합니다.
        """
        import subprocess
        import ast

        start_time = time.time()

        # 먼저 구문 검사
        try:
            ast.parse(code)
        except SyntaxError as e:
            return {
                "success": False,
                "logs": f"구문 에러: {str(e)}",
                "metrics": {},
                "exit_code": 1,
                "duration_seconds": 0.0,
            }

        try:
            with tempfile.TemporaryDirectory(prefix=f"research_{experiment_id}_") as tmp_dir:
                tmp_path = Path(tmp_dir)
                code_file = tmp_path / "main_experiment.py"
                code_file.write_text(code, encoding="utf-8")

                # 환경변수 구성
                run_env = os.environ.copy()
                run_env["EXPERIMENT_ID"] = experiment_id
                if env_vars:
                    run_env.update({k: v for k, v in env_vars.items() if v})

                # 의존성 설치 (선택)
                if requirements:
                    req_file = tmp_path / "requirements.txt"
                    req_file.write_text(requirements, encoding="utf-8")
                    try:
                        subprocess.run(
                            ["pip", "install", "-r", str(req_file), "--quiet"],
                            capture_output=True,
                            timeout=120,
                            env=run_env,
                        )
                    except Exception as e:
                        logger.warning(f"의존성 설치 실패 (계속 진행): {e}")

                # 코드 실행
                result = subprocess.run(
                    ["python3", str(code_file)],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    cwd=str(tmp_path),
                    env=run_env,
                )

                logs = result.stdout + result.stderr
                exit_code = result.returncode
                success = exit_code == 0
                metrics = self._extract_metrics_from_logs(logs)
                duration = time.time() - start_time

                return {
                    "success": success,
                    "logs": f"[FALLBACK MODE - 로컬 실행]\n{logs}",
                    "metrics": metrics,
                    "exit_code": exit_code,
                    "duration_seconds": round(duration, 2),
                }

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return {
                "success": False,
                "logs": f"실행 타임아웃 ({self.timeout_seconds}초 초과)",
                "metrics": {},
                "exit_code": -1,
                "duration_seconds": round(duration, 2),
            }
        except Exception as e:
            duration = time.time() - start_time
            return {
                "success": False,
                "logs": f"로컬 실행 에러: {str(e)}",
                "metrics": {},
                "exit_code": -1,
                "duration_seconds": round(duration, 2),
            }

    def _generate_dockerfile(self, requirements: str) -> str:
        """동적 Dockerfile을 생성합니다."""
        lines = [
            f"FROM {self.base_image}",
            "WORKDIR /experiment",
            "COPY . /experiment/",
        ]

        if requirements:
            lines.extend([
                "COPY requirements.txt /experiment/requirements.txt",
                "RUN pip install --no-cache-dir -r requirements.txt",
            ])

        lines.append('CMD ["python", "main_experiment.py"]')

        return "\n".join(lines)

    def _generate_result_collector(self) -> str:
        """결과 수집 헬퍼 스크립트를 생성합니다."""
        return '''"""실험 결과를 JSON으로 저장하는 헬퍼."""
import json
import os

def save_metrics(metrics: dict, path: str = "/experiment/results.json"):
    """메트릭을 JSON 파일로 저장합니다."""
    with open(path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"METRICS_JSON:{json.dumps(metrics)}")
'''

    def _extract_metrics_from_logs(self, logs: str) -> Dict:
        """실행 로그에서 메트릭 JSON을 추출합니다."""
        metrics = {}

        for line in logs.split("\n"):
            line = line.strip()

            # METRICS_JSON:{...} 패턴 검색
            if "METRICS_JSON:" in line:
                try:
                    json_str = line.split("METRICS_JSON:", 1)[1].strip()
                    metrics.update(json.loads(json_str))
                except (json.JSONDecodeError, IndexError):
                    pass

            # wandb 로그에서 메트릭 추출 시도
            if "accuracy" in line.lower() or "loss" in line.lower():
                try:
                    # "accuracy: 0.85" 같은 패턴
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip().lower().replace(" ", "_")
                        val = parts[1].strip()
                        try:
                            metrics[key] = float(val)
                        except ValueError:
                            pass
                except Exception:
                    pass

        return metrics

    @property
    def is_available(self) -> bool:
        """Docker 연결 상태를 반환합니다."""
        return self._initialized

    def cleanup_images(self, prefix: str = "research-exp-"):
        """실험용 Docker 이미지를 정리합니다."""
        if not self._initialized:
            return

        try:
            images = self._client.images.list()
            for image in images:
                for tag in (image.tags or []):
                    if tag.startswith(prefix):
                        self._client.images.remove(image.id, force=True)
                        logger.info(f"Docker 이미지 삭제: {tag}")
        except Exception as e:
            logger.warning(f"Docker 이미지 정리 실패: {e}")

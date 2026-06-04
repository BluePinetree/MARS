"""
Code execution tools used by the Executor agent.

Contract:
- Always save full stdout/stderr to artifact files.
- Return compact summaries and file paths only.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    success: bool
    stdout: str
    stderr: str
    return_code: int
    execution_time_seconds: float
    files_created: list[str]
    error_message: str = ""
    artifact_dir: str = ""
    stdout_path: str = ""
    stderr_path: str = ""
    summary: str = ""

    def to_report(self) -> str:
        """Return a compact report suitable for LLM context."""
        status = "success" if self.success else "failed"
        lines = [
            "[execution result]",
            f"status: {status}",
            f"return_code: {self.return_code}",
            f"execution_time_seconds: {self.execution_time_seconds:.2f}",
        ]

        if self.summary:
            lines.append(f"summary: {self.summary}")
        if self.error_message and self.error_message != self.summary:
            lines.append(f"error: {self.error_message}")

        if self.artifact_dir:
            lines.append(f"artifact_dir: {self.artifact_dir}")
        if self.stdout_path:
            lines.append(f"stdout_log: {self.stdout_path}")
        if self.stderr_path:
            lines.append(f"stderr_log: {self.stderr_path}")

        if self.files_created:
            shown = self.files_created[:10]
            lines.append("created_files:")
            lines.extend([f"- {path}" for path in shown])
            if len(self.files_created) > len(shown):
                lines.append(f"- ... and {len(self.files_created) - len(shown)} more")

        return "\n".join(lines)


class CodeExecutorInterface:
    async def execute(
        self,
        code: str,
        language: str = "python",
        timeout: int = 300,
        requirements: list[str] | None = None,
    ) -> ExecutionResult:
        raise NotImplementedError

    async def execute_shell(self, command: str, timeout: int = 60) -> ExecutionResult:
        raise NotImplementedError


class LocalCodeExecutor(CodeExecutorInterface):
    """Run code locally with isolated run directories."""

    def __init__(self, workspace_dir: str = "./workspace") -> None:
        self._workspace_dir = Path(workspace_dir).resolve()
        self._workspace_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write_logs(run_dir: Path, stdout: str, stderr: str) -> tuple[str, str]:
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        stdout_path.write_text(stdout or "", encoding="utf-8", errors="ignore")
        stderr_path.write_text(stderr or "", encoding="utf-8", errors="ignore")
        return str(stdout_path), str(stderr_path)

    @staticmethod
    def _summarize_output(success: bool, stdout: str, stderr: str) -> str:
        if success:
            for line in stdout.splitlines():
                trimmed = line.strip()
                if trimmed:
                    return trimmed[:300]
            return "Execution finished successfully."

        for line in stderr.splitlines():
            trimmed = line.strip()
            if trimmed:
                return trimmed[:300]

        for line in stdout.splitlines():
            trimmed = line.strip()
            if trimmed:
                return trimmed[:300]

        return "Execution failed without explicit error output."

    async def execute(
        self,
        code: str,
        language: str = "python",
        timeout: int = 300,
        requirements: list[str] | None = None,
    ) -> ExecutionResult:
        if language != "python":
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=f"Unsupported language: {language}",
                return_code=-1,
                execution_time_seconds=0.0,
                files_created=[],
                error_message=f"Unsupported language: {language}",
                summary=f"Unsupported language: {language}",
            )

        run_dir = self._workspace_dir / f"run_{int(time.time() * 1000)}"
        run_dir.mkdir(parents=True, exist_ok=True)

        if requirements:
            await self._install_requirements(requirements, run_dir)

        code_file = run_dir / "experiment.py"
        code_file.write_text(code, encoding="utf-8")

        files_before = {path for path in run_dir.rglob("*") if path.is_file()}

        start_time = time.time()
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(code_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(run_dir),
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                elapsed = time.time() - start_time
                summary = f"Execution timed out after {timeout} seconds."
                stdout_path, stderr_path = self._write_logs(run_dir, "", summary)
                return ExecutionResult(
                    success=False,
                    stdout="",
                    stderr=summary,
                    return_code=-1,
                    execution_time_seconds=elapsed,
                    files_created=[],
                    error_message=summary,
                    artifact_dir=str(run_dir),
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    summary=summary,
                )

            elapsed = time.time() - start_time
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            success = process.returncode == 0

            stdout_path, stderr_path = self._write_logs(run_dir, stdout, stderr)

            files_after = {path for path in run_dir.rglob("*") if path.is_file()}
            new_files = sorted(
                str(path.relative_to(run_dir))
                for path in (files_after - files_before)
                if path.name not in {"stdout.log", "stderr.log"}
            )

            summary = self._summarize_output(success, stdout, stderr)
            return ExecutionResult(
                success=success,
                stdout=stdout,
                stderr=stderr,
                return_code=process.returncode or 0,
                execution_time_seconds=elapsed,
                files_created=new_files,
                artifact_dir=str(run_dir),
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                summary=summary,
                error_message="" if success else summary,
            )

        except Exception as exc:
            elapsed = time.time() - start_time
            error = f"Executor exception: {type(exc).__name__}: {exc}"
            stdout_path, stderr_path = self._write_logs(run_dir, "", error)
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=error,
                return_code=-1,
                execution_time_seconds=elapsed,
                files_created=[],
                error_message=error,
                artifact_dir=str(run_dir),
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                summary=error,
            )

    async def execute_shell(self, command: str, timeout: int = 60) -> ExecutionResult:
        shell_dir = self._workspace_dir / f"shell_{int(time.time() * 1000)}"
        shell_dir.mkdir(parents=True, exist_ok=True)

        start_time = time.time()
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workspace_dir),
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                elapsed = time.time() - start_time
                summary = f"Shell command timed out after {timeout} seconds."
                stdout_path, stderr_path = self._write_logs(shell_dir, "", summary)
                return ExecutionResult(
                    success=False,
                    stdout="",
                    stderr=summary,
                    return_code=-1,
                    execution_time_seconds=elapsed,
                    files_created=[],
                    error_message=summary,
                    artifact_dir=str(shell_dir),
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    summary=summary,
                )

            elapsed = time.time() - start_time
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            success = process.returncode == 0

            stdout_path, stderr_path = self._write_logs(shell_dir, stdout, stderr)
            summary = self._summarize_output(success, stdout, stderr)

            return ExecutionResult(
                success=success,
                stdout=stdout,
                stderr=stderr,
                return_code=process.returncode or 0,
                execution_time_seconds=elapsed,
                files_created=[],
                artifact_dir=str(shell_dir),
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                summary=summary,
                error_message="" if success else summary,
            )
        except Exception as exc:
            elapsed = time.time() - start_time
            error = f"Shell executor exception: {type(exc).__name__}: {exc}"
            stdout_path, stderr_path = self._write_logs(shell_dir, "", error)
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=error,
                return_code=-1,
                execution_time_seconds=elapsed,
                files_created=[],
                error_message=error,
                artifact_dir=str(shell_dir),
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                summary=error,
            )

    async def _install_requirements(self, requirements: list[str], run_dir: Path) -> None:
        if not requirements:
            return

        command = f"{sys.executable} -m pip install {' '.join(requirements)}"
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(run_dir),
        )
        await process.communicate()


class OpenHandsCodeExecutor(CodeExecutorInterface):
    """Run code via OpenHands API (if enabled)."""

    def __init__(
        self,
        api_url: str = "http://localhost:3000",
        timeout: int = 300,
        workspace_dir: str = "./workspace",
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._timeout = timeout
        self._workspace_dir = Path(workspace_dir).resolve()
        self._workspace_dir.mkdir(parents=True, exist_ok=True)

    async def execute(
        self,
        code: str,
        language: str = "python",
        timeout: int = 300,
        requirements: list[str] | None = None,
    ) -> ExecutionResult:
        import aiohttp

        start_time = time.time()
        run_dir = self._workspace_dir / f"openhands_{int(time.time() * 1000)}"
        run_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "code": code,
            "language": language,
            "setup_commands": [f"pip install {' '.join(requirements)}"] if requirements else [],
            "timeout": timeout,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._api_url}/api/execute",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout + 30),
                ) as response:
                    if response.status != 200:
                        text = await response.text()
                        error = f"OpenHands API error HTTP {response.status}: {text[:400]}"
                        stdout_path, stderr_path = LocalCodeExecutor._write_logs(run_dir, "", error)
                        return ExecutionResult(
                            success=False,
                            stdout="",
                            stderr=error,
                            return_code=-1,
                            execution_time_seconds=time.time() - start_time,
                            files_created=[],
                            error_message=error,
                            artifact_dir=str(run_dir),
                            stdout_path=stdout_path,
                            stderr_path=stderr_path,
                            summary=error,
                        )

                    result = await response.json()

            stdout = str(result.get("stdout", ""))
            stderr = str(result.get("stderr", ""))
            success = bool(result.get("success", False))
            return_code = int(result.get("return_code", -1))
            files_created = [str(path) for path in result.get("files_created", [])]
            summary = LocalCodeExecutor._summarize_output(success, stdout, stderr)
            stdout_path, stderr_path = LocalCodeExecutor._write_logs(run_dir, stdout, stderr)

            return ExecutionResult(
                success=success,
                stdout=stdout,
                stderr=stderr,
                return_code=return_code,
                execution_time_seconds=time.time() - start_time,
                files_created=files_created,
                artifact_dir=str(run_dir),
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                summary=summary,
                error_message="" if success else summary,
            )

        except Exception as exc:
            error = f"OpenHands connection failed: {type(exc).__name__}: {exc}"
            stdout_path, stderr_path = LocalCodeExecutor._write_logs(run_dir, "", error)
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=error,
                return_code=-1,
                execution_time_seconds=time.time() - start_time,
                files_created=[],
                error_message=error,
                artifact_dir=str(run_dir),
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                summary=error,
            )

    async def execute_shell(self, command: str, timeout: int = 60) -> ExecutionResult:
        return await self.execute(code=command, language="bash", timeout=timeout)


_executor: Optional[CodeExecutorInterface] = None


def init_code_executor(
    openhands_enabled: bool = False,
    openhands_url: str = "http://localhost:3000",
    workspace_dir: str = "./workspace",
    timeout: int = 300,
) -> CodeExecutorInterface:
    """Initialize global executor implementation."""
    global _executor

    if openhands_enabled:
        _executor = OpenHandsCodeExecutor(
            api_url=openhands_url,
            timeout=timeout,
            workspace_dir=workspace_dir,
        )
        logger.info("[CodeExecutor] mode=OpenHands url=%s", openhands_url)
    else:
        _executor = LocalCodeExecutor(workspace_dir=workspace_dir)
        logger.info("[CodeExecutor] mode=Local workspace=%s", workspace_dir)

    return _executor


def _get_executor() -> CodeExecutorInterface:
    global _executor
    if _executor is None:
        _executor = LocalCodeExecutor()
    return _executor


async def _execute_code_async(
    code: str,
    language: str = "python",
    timeout: int = 300,
    requirements: str = "",
) -> str:
    executor = _get_executor()
    req_list = [item.strip() for item in requirements.split(",") if item.strip()] if requirements else None
    result = await executor.execute(
        code=code,
        language=language,
        timeout=timeout,
        requirements=req_list,
    )
    return result.to_report()


def execute_code(
    code: str,
    language: str = "python",
    timeout: int = 300,
    requirements: str = "",
) -> str:
    """Tool entrypoint: execute code and return compact report."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _execute_code_async(code, language, timeout, requirements))
                return future.result(timeout=timeout + 30)

        return asyncio.run(_execute_code_async(code, language, timeout, requirements))
    except Exception as exc:
        return "\n".join(
            [
                "[execution result]",
                "status: failed",
                f"summary: execute_code tool failed: {type(exc).__name__}: {exc}",
            ]
        )


def execute_shell_command(command: str, timeout: int = 60) -> str:
    """Tool entrypoint: execute shell command and return compact report."""
    try:
        executor = _get_executor()
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, executor.execute_shell(command, timeout))
                result = future.result(timeout=timeout + 10)
        else:
            result = asyncio.run(executor.execute_shell(command, timeout))

        return result.to_report()
    except Exception as exc:
        return "\n".join(
            [
                "[execution result]",
                "status: failed",
                f"summary: execute_shell_command tool failed: {type(exc).__name__}: {exc}",
            ]
        )


def execute_code_sync(code: str, language: str = "python") -> dict:
    """Sync wrapper for async execute_code — returns dict with success/report."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _execute_code_async(code, language, 300, ""))
                report = future.result(timeout=330)
        else:
            report = asyncio.run(_execute_code_async(code, language, 300, ""))
        return {
            "success": "status: failed" not in report.lower(),
            "report": report,
        }
    except Exception as exc:
        return {
            "success": False,
            "report": f"execute_code_sync failed: {type(exc).__name__}: {exc}",
        }


def execute_shell_sync(command: str, working_dir: str, timeout: int = 300) -> dict:
    """Sync shell execution in a specific working directory. Returns dict with return_code/stdout/stderr."""
    import subprocess
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "return_code": proc.returncode,
            "stdout": proc.stdout[:2000],
            "stderr": proc.stderr[:1000],
            "success": proc.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"return_code": -1, "error": f"timeout after {timeout}s", "success": False}
    except Exception as exc:
        return {"return_code": -1, "error": str(exc), "success": False}

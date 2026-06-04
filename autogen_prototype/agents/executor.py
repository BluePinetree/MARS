"""
Executor agent — runs src/main.py via shell and reports results.

0.4.x: AssistantAgent + FunctionTool.
Executor runs 'python src/main.py' in workspace_root.
src/main.py (written by Coder) must save results/result.json via artifacts.py.
"""

from __future__ import annotations

from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient
from autogen_core.tools import FunctionTool


_EXECUTOR_SYSTEM = """\
You are an Experiment Executor. Run the experiment and report ACTUAL results.

Procedure:
1. Call execute_shell_command with:
   - command = 'python src/main.py'
   - working_dir = the workspace_root provided in the task message
2. If return_code == 0: report SUCCESS + key output lines.
3. If return_code != 0: report the error from stderr. Do NOT fabricate metrics.
4. NEVER invent return codes, accuracy values, or file paths.

Output Contract (required format):
Status: SUCCESS or FAILED
Return code: <int>
Key output: <first 500 chars of stdout>
Artifacts: results/result.json (if exists)
"""


def make_executor_agent(model_client: ChatCompletionClient, workspace_root: str) -> AssistantAgent:
    """Create Executor agent with shell execution bound to workspace_root."""
    from tools.code_executor import execute_shell_sync, execute_code_sync

    try:
        from rsp.tool_result_budget import apply_budget
    except Exception:
        def apply_budget(result: str, max_chars: int = 4000) -> str:
            if len(result) <= max_chars:
                return result
            half = max_chars // 2
            return result[:half] + f"\n...[TRUNCATED]...\n" + result[-half:]

    def _execute_shell(command: str, working_dir: str = "", timeout: int = 300) -> str:
        wd = working_dir if working_dir else workspace_root
        result = execute_shell_sync(command, wd, timeout)
        return apply_budget(str(result), max_chars=3000)

    def _execute_code(code: str, language: str = "python") -> str:
        result = execute_code_sync(code, language)
        return apply_budget(str(result), max_chars=3000)

    tools = [
        FunctionTool(
            _execute_shell,
            name="execute_shell_command",
            description="Execute a shell command in working_dir. Returns return_code, stdout, stderr.",
        ),
        FunctionTool(
            _execute_code,
            name="execute_code",
            description="Execute Python code directly. Returns stdout, stderr, success.",
        ),
    ]

    return AssistantAgent(
        name="Executor",
        model_client=model_client,
        tools=tools,
        description=(
            "실험 코드를 실행하고 결과를 보고하는 MLOps 엔지니어. "
            "execute_shell_command로 src/main.py를 실행하고 결과를 그대로 보고한다."
        ),
        system_message=_EXECUTOR_SYSTEM,
    )


def create_executor(
    model_client: ChatCompletionClient,
    workspace_root: str = "",
    tools: list | None = None,
) -> AssistantAgent:
    """Backward-compatible wrapper. Prefer make_executor_agent when workspace_root is known."""
    if workspace_root:
        return make_executor_agent(model_client, workspace_root)
    return AssistantAgent(
        name="Executor",
        model_client=model_client,
        tools=tools or [],
        description="코드 실행과 환경 관리를 전담하는 DevOps/MLOps 엔지니어.",
        system_message=_EXECUTOR_SYSTEM,
    )

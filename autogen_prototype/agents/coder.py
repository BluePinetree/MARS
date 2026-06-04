"""
Coder agent — tool-based file writing via workspace_write.

0.4.x: AssistantAgent + FunctionTool (register_function / UserProxyAgent 불필요).
Coder writes files to disk via tools; never outputs code as plain text.
Signals completion with "FILES_WRITTEN: [list]".
"""

from __future__ import annotations

from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient
from autogen_core.tools import FunctionTool

from workspace.workspace_tools import WorkspaceReadTool, WorkspaceWriteTool, WorkspaceListTool
from workspace.code_tools import SyntaxCheckTool, ImportCheckTool


_CODER_SYSTEM = """\
You are a Research Code Engineer. You write ML experiment code to disk using tools.

Workflow:
1. Use workspace_read to read src/artifacts.py and src/config_schema.py first.
2. Use workspace_list to see what files already exist.
3. Use workspace_write to write each required file (mode='write' for new, 'append' for continuation).
4. After writing each .py file, call syntax_check.
5. After all files are written, call import_check on src/experiment_impl.py (or the main module).
6. Report "FILES_WRITTEN: [list of files]" when done — this signals routing to Critic.

Rules:
- NEVER output code as plain text or markdown blocks.
- ONLY use workspace_write to create files.
- All files go under src/ (e.g., src/models.py, src/main.py).
- src/main.py must call write_result_json() from src/artifacts.py to save results/result.json.
- Implement real domain logic (PyTorch/sklearn). No placeholder stubs.
- If a file is large, write the first half then append the rest.
"""


def make_coder_agent(model_client: ChatCompletionClient, workspace_root: str) -> AssistantAgent:
    """Create Coder agent with workspace tools bound to workspace_root."""
    write_tool = WorkspaceWriteTool()
    read_tool = WorkspaceReadTool()
    list_tool = WorkspaceListTool()
    syntax_tool = SyntaxCheckTool()
    import_tool = ImportCheckTool()

    def _workspace_write(relative_path: str, content: str, mode: str = "write") -> str:
        return write_tool.run(workspace_root, relative_path, content, mode)

    def _workspace_read(relative_path: str) -> str:
        return read_tool.run(workspace_root, relative_path)

    def _workspace_list(directory: str = "") -> str:
        return list_tool.run(workspace_root, directory)

    def _syntax_check(relative_path: str) -> str:
        return syntax_tool.run(workspace_root, relative_path)

    def _import_check(relative_path: str) -> str:
        return import_tool.run(workspace_root, relative_path)

    tools = [
        FunctionTool(_workspace_write, name="workspace_write",
                     description=write_tool.description),
        FunctionTool(_workspace_read, name="workspace_read",
                     description=read_tool.description),
        FunctionTool(_workspace_list, name="workspace_list",
                     description=list_tool.description),
        FunctionTool(_syntax_check, name="syntax_check",
                     description=syntax_tool.description),
        FunctionTool(_import_check, name="import_check",
                     description=import_tool.description),
    ]

    return AssistantAgent(
        name="Coder",
        model_client=model_client,
        tools=tools,
        description=(
            "ML 실험 코드를 workspace 도구를 이용해 파일로 작성하는 엔지니어. "
            "코드를 텍스트로 출력하지 않고, workspace_write 도구로만 파일을 작성한다."
        ),
        system_message=_CODER_SYSTEM,
    )


def create_coder(
    model_client: ChatCompletionClient,
    workspace_root: str = "",
    tools: list | None = None,
) -> AssistantAgent:
    """Backward-compatible wrapper. Prefer make_coder_agent when workspace_root is known."""
    if workspace_root:
        return make_coder_agent(model_client, workspace_root)
    return AssistantAgent(
        name="Coder",
        model_client=model_client,
        tools=tools or [],
        description="Python 코드 작성을 전담하는 ML 엔지니어.",
        system_message=_CODER_SYSTEM,
    )

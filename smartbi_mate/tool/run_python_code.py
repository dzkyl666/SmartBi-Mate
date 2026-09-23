"""Python 代码执行工具（V1 仅支持 local 执行器）。"""

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from smartbi_mate.code.executor_base import ExecutorBase
from smartbi_mate.code.local_executor import LocalExecutor
from smartbi_mate.utils import log


class PythonCodeInput(BaseModel):
    reasoning: str = Field(description="使用此工具运行 Python 代码的原因")
    code: str = Field(description="要执行的 Python 代码")


def _create_executor() -> ExecutorBase:
    """根据配置创建代码执行器（V1 固定使用 LocalExecutor）。"""
    log("Creating LocalExecutor (V1 only supports local execution)")
    return LocalExecutor()


@tool("run_python_code", args_schema=PythonCodeInput, return_direct=False, infer_schema=True)
def run_python_code(reasoning: str, code: str) -> str:
    """Run python code string. Note: Only print outputs are visible, function return values will be ignored. Use print statements to see results.
    Returns:
        str: The print outputs of the python code
    """
    log(f"Run Python Code, Reasoning: {reasoning}")

    try:
        executor = _create_executor()
        log(f"Using {executor.__class__.__name__} for code execution")
        success, output = executor.run_code(code)
        if success:
            return output
        else:
            return f"Error: {output}"
    except Exception as e:
        log(f"Failed to create executor: {e}")
        # Fallback to LocalExecutor if configuration fails
        log("Falling back to LocalExecutor")
        executor = LocalExecutor()
        success, output = executor.run_code(code)
        if success:
            return output
        else:
            return f"Error: {output}"

"""主 Agent 图构建与执行逻辑（中文对话式 BI）。

学习地图：
- get_sql_tools(): 把编译后的 SQL 子图包装成 StructuredTool，挂给主 Agent
- _build_graph_core(): 组装主图的节点(llm_node/ask_human/use_tool)和边
- build_agent_graph_sync/async(): 对外暴露的同步/异步构建入口
"""

import datetime
import json
import logging
import traceback
from collections.abc import Callable
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langchain_openai.chat_models.base import BaseChatOpenAI
from langgraph.constants import START
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.base import BaseStore
from langgraph.types import Checkpointer, Send, interrupt
from pydantic import BaseModel, Field

from openchatbi import config
from openchatbi.catalog import CatalogStore
from openchatbi.constants import datetime_format
from openchatbi.context_config import get_context_config
from openchatbi.context_manager import ContextManager
from openchatbi.graph_state import AgentState, InputState, OutputState
from openchatbi.llm.llm import call_llm_chat_model_with_retry, get_llm
from openchatbi.prompts.system_prompt import get_agent_prompt_template
from openchatbi.text2sql.sql_graph import build_sql_graph
from openchatbi.tool.ask_human import AskHuman
from openchatbi.tool.memory import get_memory_tools
from openchatbi.tool.run_python_code import run_python_code
from openchatbi.tool.save_report import save_report
from openchatbi.tool.search_knowledge import search_knowledge, search_schema, show_schema
from openchatbi.utils import get_text_from_content, log, recover_incomplete_tool_calls

logger = logging.getLogger(__name__)


def ask_human(state: AgentState) -> dict[str, Any]:
    """Node function to ask human for additional information or clarification.

    Args:
        state (AgentState): The current graph state containing messages and context.

    Returns:
        dict: Updated state with human feedback as a tool message and user input.
    """
    last_message = cast(AIMessage, state["messages"][-1])
    tool_call = last_message.tool_calls[0]
    tool_call_id = tool_call["id"]
    args = tool_call["args"]
    user_feedback = interrupt({"text": args["question"], "buttons": args.get("options", None)})
    tool_message = [{"tool_call_id": tool_call_id, "type": "tool", "content": user_feedback}]
    return {
        "messages": tool_message,
        "history_messages": [AIMessage(args["question"]), HumanMessage(user_feedback)],
        "user_input": user_feedback,
    }


class CallSQLGraphInput(BaseModel):
    reasoning: str = Field(
        description="Explanation of why Text2SQL tool is needed",
    )
    context: str | dict[str, Any] | list[dict[str, Any]] | list[str] = Field(
        description="""Context payload passed to Text2SQL.
        Prefer a structured format to preserve information while isolating scope:
        - Shared Context: stable business background, entities, metrics, key filters
        - Current Subtask (User's latest question): The ONLY specific query to execute NOW.
        - Carry-over From Previous Step: prior SQL/result and the exact delta to apply (optional)
        - Deferred Tasks: remaining stages to ignore for now (optional)""",
    )
    visualize: bool = Field(
        default=True,
        description=(
            "Whether this Text2SQL call should generate visualization DSL for UI display. "
            "Set to false for intermediate data retrieval used by downstream analysis tools."
        ),
    )


# Text2SQL 工具描述（中文）
_TEXT2SQL_TOOL_DESCRIPTION = """Text2SQL 工具：根据用户的中文问题和上下文，生成并执行 SQL 查询，同时生成可视化图表配置。

返回：
    str: 包含 SQL、查询结果和可视化状态的格式化响应。

重要说明：
- 不要用此工具探索数据库结构。先用 search_schema 发现表结构，用 show_schema 查看已知表的详情
- 如果用户想更换图表类型或样式，把需求写在问题里
- 当调用只是为了获取中间数据（不需要展示图表）时，设置 visualize=false
- 用户的中文问题直接传入即可，不需要翻译成英文
- 分步任务中，只传当前子任务的上下文，其他步骤放在 Deferred Tasks 里
"""


def _normalize_text2sql_context(context: str | dict[str, Any] | list[dict[str, Any]] | list[str]) -> str:
    """Normalize tool context to the string payload expected by SQL graph."""
    if isinstance(context, str):
        return context
    try:
        return json.dumps(context, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(context)


def _format_sql_response(sql_graph_response: dict[str, Any]) -> str:
    """Format SQL graph response into a standardized string format.

    Args:
        sql_graph_response: The response dictionary from the SQL graph

    Returns:
        str: Formatted response string
    """
    sql = sql_graph_response.get("sql", "")
    data = sql_graph_response.get("data", "")
    visualization_dsl = sql_graph_response.get("visualization_dsl", {})

    response_parts: list[str] = []
    if sql:
        response_parts.append(f"SQL Query:\n```sql\n{sql}\n```")
    if data:
        response_parts.append(f"\nQuery Results (CSV format):\n```csv\n{data}\n```")

    # Include visualization status
    if visualization_dsl and "error" not in visualization_dsl:
        chart_type = visualization_dsl.get("chart_type", "unknown")
        response_parts.append(
            f"\nVisualization Created: {chart_type} chart has been automatically generated and will be displayed in the UI."
        )
    elif visualization_dsl and "error" in visualization_dsl:
        response_parts.append(f"\nVisualization Error: {visualization_dsl['error']}")

    return "\n\n".join(response_parts) if response_parts else "No results returned."


def get_sql_tools(sql_graph: CompiledStateGraph[Any, None, Any, Any], sync_mode: bool = False) -> StructuredTool:
    """Create SQL generation tool from compiled SQL graph.

    Args:
        sql_graph (CompiledStateGraph): The compiled SQL generation subgraph.
        sync_mode (bool): Whether to create synchronous or asynchronous tools

    Returns:
        function: Tool function for SQL generation.
    """

    def call_sql_graph_sync(
        reasoning: str,
        context: str | dict[str, Any] | list[dict[str, Any]] | list[str],
        config: RunnableConfig,
        visualize: bool = True,
    ) -> str:
        """Sync node function for Text2SQL tool"""
        normalized_context = _normalize_text2sql_context(context)
        log(f"Call SQL graph (sync) with reasoning: {reasoning}, visualize: {visualize}, context: {normalized_context}")
        try:
            sql_graph_response = sql_graph.invoke(
                {"messages": normalized_context, "visualize": visualize}, config=config
            )
            return _format_sql_response(sql_graph_response)
        except GraphInterrupt as e:
            log(f"Sql graph interrupted:\n{repr(e)}")
            raise e
        except Exception as e:
            log(f"Run sql graph error:\n{repr(e)}")
            traceback.print_exc()
        return "Error occurred when calling Text2SQL tool."

    async def call_sql_graph_async(
        reasoning: str,
        context: str | dict[str, Any] | list[dict[str, Any]] | list[str],
        config: RunnableConfig,
        visualize: bool = True,
    ) -> str:
        """Async node function for Text2SQL tool"""
        normalized_context = _normalize_text2sql_context(context)
        log(
            f"Call SQL graph (async) with reasoning: {reasoning}, visualize: {visualize}, context: {normalized_context}"
        )
        try:
            sql_graph_response = await sql_graph.ainvoke(
                {"messages": normalized_context, "visualize": visualize}, config=config
            )
            return _format_sql_response(sql_graph_response)
        except GraphInterrupt as e:
            log(f"Sql graph interrupted:\n{repr(e)}")
            raise e
        except Exception as e:
            log(f"Run sql graph error:\n{repr(e)}")
            traceback.print_exc()
        return "Error occurred when calling Text2SQL tool."

    if sync_mode:
        return StructuredTool.from_function(
            func=call_sql_graph_sync,
            name="text2sql",
            description=_TEXT2SQL_TOOL_DESCRIPTION,
            args_schema=CallSQLGraphInput,
            return_direct=False,
        )
    else:
        return StructuredTool.from_function(
            coroutine=call_sql_graph_async,
            name="text2sql",
            description=_TEXT2SQL_TOOL_DESCRIPTION,
            args_schema=CallSQLGraphInput,
            return_direct=False,
        )


def agent_llm_call(
    llm: BaseChatModel,
    tools: list[Any],
    context_manager: ContextManager | None = None,
) -> Callable[..., Any]:
    """Create llm call function to generate reasoning and determine next node based on tool calls in LLM response.

    Args:
        llm (BaseChatModel): The LLM for agent decision-making.
        tools: List of tools.
        context_manager: Optional context manager for handling long conversations.

    Returns:
        function: function that processes state and determines next node.
    """

    # OpenAI models support strict tool calling
    if isinstance(llm, BaseChatOpenAI):
        llm_with_tools = llm.bind_tools(tools, strict=True)
    else:
        llm_with_tools = llm.bind_tools(tools)

    def _call_model(state: AgentState) -> dict[str, Any]:
        # First, check and recover any incomplete tool calls
        recovery_ops = recover_incomplete_tool_calls(state)
        if recovery_ops:
            return {"messages": recovery_ops, "agent_next_node": "llm_node"}

        messages = state["messages"]
        final_messages: list[HumanMessage | AIMessage] = []
        if isinstance(messages[-1], HumanMessage):
            final_messages.append(messages[-1])

        # Apply context management if available (before processing)
        if context_manager:
            original_count = len(messages)
            context_manager.manage_context_messages(messages)  # type: ignore[arg-type]
            if len(messages) != original_count:
                logger.info(f"Context management: modified messages from {original_count} to {len(messages)}")

        system_prompt = get_agent_prompt_template().replace(
            "[time_field_placeholder]", datetime.datetime.now().strftime(datetime_format)
        )

        response = call_llm_chat_model_with_retry(
            cast(BaseChatModel, llm_with_tools),
            ([SystemMessage(system_prompt)] + messages),
            streaming_tokens=True,
            bound_tools=tools,
            parallel_tool_call=True,
        )
        if isinstance(response, AIMessage):
            tool_calls = response.tool_calls
            print("Tool Call:", ", ".join(tool["name"] for tool in tool_calls))
            if tool_calls:
                # Group tool calls by type for parallel routing
                ask_human_calls = [call for call in tool_calls if call["name"] == "AskHuman"]
                normal_tool_calls = [call for call in tool_calls if call["name"] != "AskHuman"]

                # Create Send objects for parallel routing
                sends: list[Send] = []
                if ask_human_calls:
                    # Create message with only AskHuman calls
                    ask_human_msg = AIMessage(content=response.content, tool_calls=ask_human_calls)
                    sends.append(Send("ask_human", {"messages": [ask_human_msg]}))

                if normal_tool_calls:
                    # Create message with only normal tool calls
                    tool_msg = AIMessage(content=response.content, tool_calls=normal_tool_calls)
                    sends.append(Send("use_tool", {"messages": [tool_msg]}))

                return {"messages": [response], "history_messages": final_messages, "sends": sends}
            else:
                final_answer = get_text_from_content(response.content)
                final_messages.append(AIMessage(response.content))
                return {
                    "messages": [response],
                    "final_answer": final_answer,
                    "history_messages": final_messages,
                    "agent_next_node": END,
                }
        elif response is None:
            return {
                "messages": [AIMessage("Sorry, the LLM service is currently unavailable.")],
                "history_messages": final_messages,
                "agent_next_node": END,
            }
        else:
            return {"messages": [response], "history_messages": final_messages, "agent_next_node": END}

    return _call_model


def _build_graph_core(
    catalog: CatalogStore,
    sync_mode: bool,
    checkpointer: Checkpointer | None,
    memory_store: BaseStore | None,
    memory_tools: list[Any] | None,
    enable_context_management: bool = True,
    llm_provider: str | None = None,
) -> CompiledStateGraph[AgentState, None, InputState, OutputState]:
    """核心图构建逻辑（同步/异步共用）。

    Args:
        catalog: 数据目录存储
        sync_mode: 是否使用同步模式
        checkpointer: 状态持久化检查点
        memory_store: 长期记忆存储
        memory_tools: 记忆工具列表
        enable_context_management: Whether to enable context management

    Returns:
        CompiledStateGraph: Compiled agent graph ready for execution
    """
    sql_graph = build_sql_graph(catalog, checkpointer, cast(BaseStore, memory_store), llm_provider=llm_provider)
    call_sql_graph_tool = get_sql_tools(sql_graph=sql_graph, sync_mode=sync_mode)

    # 使用传入的 memory tools 或自动创建
    memory_tools_for_graph: list[Any] | None = list(memory_tools) if memory_tools else None
    if not memory_tools_for_graph:
        memory_tools_for_graph = get_memory_tools(get_llm(llm_provider), sync_mode=sync_mode, store=memory_store)

    # V1 工具列表（已移除 data_analysis_tool 和 MCP tools）
    normal_tools: list[Any] = [
        search_knowledge,
        search_schema,
        show_schema,
        call_sql_graph_tool,
        run_python_code,
        save_report,
    ]
    if memory_tools_for_graph:
        normal_tools.extend(memory_tools_for_graph)

    # Initialize context manager if enabled
    context_manager = None
    if enable_context_management:
        context_manager = ContextManager(llm=get_llm(llm_provider), config=get_context_config())

    tool_node = ToolNode(normal_tools)

    # Define the agent graph
    graph = StateGraph(AgentState, input_schema=InputState, output_schema=OutputState)

    # Add nodes to the graph
    agent_tools: list[Any] = [*normal_tools, AskHuman]
    graph.add_node("llm_node", agent_llm_call(get_llm(llm_provider), agent_tools, context_manager))
    graph.add_node("ask_human", ask_human)
    graph.add_node("use_tool", tool_node)

    # Add edges between nodes
    graph.add_edge(START, "llm_node")
    graph.add_edge("ask_human", "llm_node")
    graph.add_edge("use_tool", "llm_node")

    # Add conditional routing from llm node
    def route_tools(state: AgentState) -> str | list[Send]:
        # Only use sends if the last message came from the llm node (has tool_calls)
        last_message = state["messages"][-1] if state["messages"] else None
        if (
            last_message
            and isinstance(last_message, AIMessage)
            and last_message.tool_calls
            and "sends" in state
            and state["sends"]
        ):
            return state["sends"]  # Return Send objects for parallel execution
        next_node = state.get("agent_next_node")
        if next_node:
            return next_node  # Return single node name
        return END

    graph.add_conditional_edges(
        "llm_node",
        route_tools,
        # mapping of paths to node names (for single routing)
        {
            "llm_node": "llm_node",
            "ask_human": "ask_human",
            "use_tool": "use_tool",
            END: END,
        },
    )

    compiled_graph = graph.compile(name="agent_graph", checkpointer=checkpointer, store=memory_store)
    return compiled_graph


def build_agent_graph_sync(
    catalog: CatalogStore,
    checkpointer: Checkpointer | None = None,
    memory_store: BaseStore | None = None,
    enable_context_management: bool = True,
    llm_provider: str | None = None,
) -> CompiledStateGraph[Any, None, Any, Any]:
    """Build the main agent graph with all nodes and edges (sync version).

    Args:
        catalog: Catalog store containing schema information.
        checkpointer: The Checkpointer for state persistence (short memory). If None, no short memory.
        memory_store: The BaseStore to use for long-term memory. If None, will auto assign according to sync_mode.
        enable_context_management: Whether to enable context management for long conversations.

    Returns:
        CompiledStateGraph: Compiled agent graph ready for execution.
    """
    return _build_graph_core(
        catalog=catalog,
        sync_mode=True,
        checkpointer=checkpointer,
        memory_store=memory_store,
        memory_tools=None,
        enable_context_management=enable_context_management,
        llm_provider=llm_provider,
    )


async def build_agent_graph_async(
    catalog: CatalogStore,
    checkpointer: Checkpointer | None = None,
    memory_store: BaseStore | None = None,
    memory_tools: list[Any] | None = None,
    enable_context_management: bool = True,
    llm_provider: str | None = None,
) -> CompiledStateGraph[Any, None, Any, Any]:
    """构建主 Agent 图（异步版本）。

    Args:
        catalog: 数据目录存储
        checkpointer: 状态持久化检查点
        memory_store: 长期记忆存储
        memory_tools: 记忆工具列表
        enable_context_management: 是否启用上下文管理

    Returns:
        CompiledStateGraph: 编译好的 Agent 图
    """
    return _build_graph_core(
        catalog=catalog,
        sync_mode=False,
        checkpointer=checkpointer,
        memory_store=memory_store,
        memory_tools=memory_tools,
        enable_context_management=enable_context_management,
        llm_provider=llm_provider,
    )

"""SmartBI Mate：基于 Streamlit 的流式中文 BI 对话界面（带可折叠思考过程）。"""

import asyncio
import atexit
import sys
import traceback
import uuid
from pathlib import Path

import plotly.graph_objects as go

try:
    import pysqlite3 as sqlite3
except ImportError:  # pragma: no cover
    import sqlite3
import streamlit as st

sys.modules["sqlite3"] = sqlite3

from langgraph.types import Command  # noqa: E402

from smartbi_mate import config as smartbi_mate_config  # noqa: E402
from smartbi_mate.llm.llm import list_llm_providers  # noqa: E402
from smartbi_mate.streaming import AgentStreamProcessor, StreamStep, StreamToken  # noqa: E402
from smartbi_mate.utils import log  # noqa: E402
from sample_ui.async_graph_manager import AsyncGraphManager  # noqa: E402
from sample_ui.history_loader import load_session_history  # noqa: E402
from sample_ui.plotly_utils import visualization_dsl_to_gradio_plot  # noqa: E402

# Configuration
st.set_page_config(page_title="SmartBI Mate - 智能数据分析", page_icon="📊", layout="wide")

# 注入自定义样式（中文化 + 现代 BI 风格）
try:
    from sample_ui.style import custom_css
    st.markdown(custom_css, unsafe_allow_html=True)
except Exception:
    pass

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "graph_manager" not in st.session_state:
    st.session_state.graph_manager = AsyncGraphManager()
if "session_interrupts" not in st.session_state:
    st.session_state.session_interrupts = {}
if "event_loop" not in st.session_state:
    st.session_state.event_loop = None
if "loaded_thread" not in st.session_state:
    st.session_state.loaded_thread = None


async def process_user_message_stream(
    message: str, user_id: str, session_id: str, llm_provider: str | None, thinking_container, response_container
):
    """
    Process user message through the smartbi_mate graph with real-time updates
    Updates the thinking_container and response_container as processing happens
    """
    thinking_steps = []
    top_level_step_number = 0
    # Hierarchical counters keyed by stream depth:
    # level 0 => top-level steps, level 1+ => nested sub-steps.
    step_counters: dict[int, int] = {0: 0}
    final_response = ""
    plot_figure = None

    # Initialize graph if needed
    if not st.session_state.graph_manager._initialized:
        await st.session_state.graph_manager.initialize()
    graph = await st.session_state.graph_manager.get_graph(llm_provider)

    user_session_id = f"{user_id}-{session_id}"

    # Check for interrupts
    if st.session_state.session_interrupts.get(user_session_id, False):
        stream_input = Command(resume=message)
    else:
        stream_input = {"messages": [{"role": "user", "content": message}]}

    from smartbi_mate.observability.tracing import build_run_config

    config = build_run_config(user_id=user_id, session_id=session_id)

    # Use empty container for real-time updates
    thinking_placeholder = thinking_container.empty()

    # Build content chronologically - all events in time order
    base_content = "🔄 **正在处理...**\n\n"
    chronological_content = ""  # All content in time order
    # Tracks which layer's tokens are currently being appended, so consecutive
    # tokens from the same source are grouped under one header. "main" = main
    # agent, a namespace tuple = a sub-agent, None = reset (after a step line).
    current_token_layer = None

    def update_display():
        full_content = base_content + chronological_content
        thinking_placeholder.markdown(full_content)

    # Initial display
    update_display()

    # Stream through the graph using the shared event parser so the CLI, the
    # HTTP API and this UI all surface the same intermediate steps.
    processor = AgentStreamProcessor()
    async for namespace, event_type, event_value in graph.astream(
        stream_input, config=config, stream_mode=["updates", "messages"], subgraphs=True, debug=True
    ):
        for event in processor.process(namespace, event_type, event_value):
            if isinstance(event, StreamToken):
                if event.is_final:
                    # Main agent streaming its (intermediate/final) answer.
                    final_response += event.text
                    if current_token_layer != "main":
                        chronological_content += "\n\n**🤖 回答：** "
                        current_token_layer = "main"
                else:
                    # Sub-agent (data analysis) thinking tokens.
                    token_layer = ("think", event.level, event.label)
                    if current_token_layer != token_layer:
                        chronological_content += f"\n\n{'　' * event.level}💭 *{event.label} 思考中：* "
                        current_token_layer = token_layer
                chronological_content += event.text
                update_display()

            elif isinstance(event, StreamStep):
                desc = event.text

                # Building the Plotly figure is UI-specific, so it stays here.
                # The shared parser hands us the DSL plus the latest CSV data.
                if event.kind == "visualization":
                    data_csv = event.data.get("data")
                    visualization_dsl = event.data.get("visualization_dsl")
                    if not data_csv:
                        # Match prior behavior: no chart without data.
                        continue
                    try:
                        plot_figure, plot_description = visualization_dsl_to_gradio_plot(data_csv, visualization_dsl)
                        desc = f"📊 Generated visualization: {plot_description}"
                    except Exception as e:
                        desc = f"⚠️ Visualization error: {str(e)}"

                thinking_steps.append(desc)
                if chronological_content and not chronological_content.endswith("\n\n"):
                    chronological_content += "\n\n"
                if event.level == 0:
                    top_level_step_number += 1
                    step_counters[0] = top_level_step_number
                    # Reset nested counters when entering a new top-level step.
                    step_counters = {k: v for k, v in step_counters.items() if k == 0}
                    chronological_content += f"**步骤 {top_level_step_number}：** {desc}\n\n"
                else:
                    # Ensure we always have a top-level context, even if a
                    # nested step appears first due to event ordering.
                    if step_counters.get(0, 0) == 0:
                        top_level_step_number = 1
                        step_counters[0] = top_level_step_number

                    step_counters[event.level] = step_counters.get(event.level, 0) + 1
                    # Drop deeper levels when we move back up.
                    step_counters = {k: v for k, v in step_counters.items() if k <= event.level}

                    step_number_parts = [
                        str(step_counters[level]) for level in sorted(step_counters.keys()) if level <= event.level
                    ]
                    hierarchical_step_number = ".".join(step_number_parts)
                    chronological_content += (
                        f"{'　' * event.level}↳ 步骤 {hierarchical_step_number} " f"[{event.label}] {desc}\n\n"
                    )
                # Reset token grouping so the next streamed tokens get a header.
                current_token_layer = None
                update_display()

    # Check for interrupts in final state
    state = await graph.aget_state(config)
    if state.interrupts:
        log(f"State interrupts: {state.interrupts}")
        output_content = state.interrupts[0].value.get("text", "")
        if "buttons" in state.interrupts[0].value:
            output_content += str(state.interrupts[0].value.get("buttons"))
        final_response += output_content

        # Append interrupt content to chronological content
        chronological_content += output_content
        update_display()

        st.session_state.session_interrupts[user_session_id] = True
    else:
        st.session_state.session_interrupts[user_session_id] = False

    # Final update - add completion message to chronological content
    # Add some spacing if the last content didn't end with newlines
    if not chronological_content.endswith("\n\n"):
        chronological_content += "\n\n"
    chronological_content += "✅ **分析完成！**"
    update_display()

    # Extract final answer (last part without tool calls) and display outside thinking
    if final_response:
        # Find the last occurrence of tool usage to separate final answer
        lines = final_response.split("\n")
        final_answer_lines = []
        collecting_final = False

        for line in reversed(lines):
            if "Use tool:" in line or "Using tools:" in line or "Using tool:" in line:
                break
            final_answer_lines.append(line)
            collecting_final = True

        if collecting_final and final_answer_lines:
            # Reverse back to correct order
            final_answer_lines.reverse()
            final_answer_text = "\n".join(final_answer_lines).strip()

            if final_answer_text:
                with response_container:
                    processed_final_answer_text = process_download_links(final_answer_text)
                    render_content_with_downloads(processed_final_answer_text)

    # Final update to response container - only show plot if available (text response is in thinking container)
    with response_container:
        if plot_figure:
            st.plotly_chart(plot_figure, width="stretch", key=str(uuid.uuid4()))

    # Extract final answer for separate storage
    final_answer_text = ""
    if final_response:
        lines = final_response.split("\n")
        final_answer_lines = []
        collecting_final = False

        for line in reversed(lines):
            if "Use tool:" in line or "Using tools:" in line or "Using tool:" in line:
                break
            final_answer_lines.append(line)
            collecting_final = True

        if collecting_final and final_answer_lines:
            final_answer_lines.reverse()
            final_answer_text = "\n".join(final_answer_lines).strip()

    return final_response, plot_figure, thinking_steps, chronological_content, final_answer_text


async def _load_history_async(user_id: str, session_id: str, llm_provider: str | None) -> list[dict]:
    """Initialize the graph if needed and load persisted history for a thread."""
    if not st.session_state.graph_manager._initialized:
        await st.session_state.graph_manager.initialize()
    graph = await st.session_state.graph_manager.get_graph(llm_provider)
    return await load_session_history(graph, user_id, session_id)


def restore_history_if_needed(user_id: str, session_id: str, llm_provider: str | None) -> None:
    """Load checkpoint history into the UI when the active thread changes.

    Runs once per thread: switching ``user_id``/``session_id`` reloads history,
    while reruns within the same thread are no-ops so live messages are never
    duplicated.
    """
    thread = f"{user_id}-{session_id}"
    if st.session_state.loaded_thread == thread:
        return

    try:
        if st.session_state.event_loop is None or st.session_state.event_loop.is_closed():
            st.session_state.event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(st.session_state.event_loop)
        loop = st.session_state.event_loop
        st.session_state.messages = loop.run_until_complete(_load_history_async(user_id, session_id, llm_provider))
    except Exception as e:
        log(f"Error restoring history for {thread}: {e}")
        st.session_state.messages = []
    finally:
        st.session_state.loaded_thread = thread


def get_available_reports() -> list[str]:
    """Get list of available report files for download."""
    try:
        # Import config here to avoid circular imports
        from smartbi_mate import config

        report_dir = Path(config.get().report_directory)
        if not report_dir.exists():
            return []

        # Get all files in the report directory
        report_files = []
        for file_path in report_dir.iterdir():
            if file_path.is_file():
                report_files.append(file_path.name)

        return sorted(report_files)
    except Exception as e:
        st.error(f"访问报告目录出错: {str(e)}")
        return []


def get_report_file_content(filename: str) -> tuple[bytes | None, str | None]:
    """Get report file content for download.

    Returns:
        tuple: (file_content_bytes, mime_type) or (None, None) if error
    """
    try:
        # Import config here to avoid circular imports
        from smartbi_mate import config

        report_dir = Path(config.get().report_directory)
        file_path = report_dir / filename

        # Security check - ensure file is within report directory
        if not file_path.exists() or not file_path.is_file():
            st.error(f"报告文件不存在: {filename}")
            return None, None

        try:
            file_path.resolve().relative_to(report_dir.resolve())
        except ValueError:
            st.error("无权访问该文件")
            return None, None

        # Determine MIME type
        mime_type_map = {
            ".md": "text/markdown",
            ".csv": "text/csv",
            ".txt": "text/plain",
            ".json": "application/json",
            ".html": "text/html",
            ".xml": "application/xml",
        }

        file_extension = file_path.suffix.lower()
        mime_type = mime_type_map.get(file_extension, "application/octet-stream")

        # Read file content
        with open(file_path, "rb") as f:
            content = f.read()

        return content, mime_type

    except Exception as e:
        st.error(f"读取报告文件出错: {str(e)}")
        return None, None


def process_download_links(content: str) -> str:
    """Process download links in content and replace them with Streamlit-compatible ones.

    Args:
        content: Message content that may contain download links

    Returns:
        str: Content with download links replaced
    """
    import re

    if not content:
        return content

    # Pattern to match both full URLs and path-only download links
    # Matches: http://localhost:8501/api/download/report/filename.ext or /api/download/report/filename.ext
    download_pattern = r"(?:https?://[^/\s]+)?/api/download/report/([^)\s\]<>]+)"

    def replace_link(match):
        filename = match.group(1)
        # Return a placeholder that we'll replace with actual download button
        return f"[DOWNLOAD_LINK:{filename}]"

    processed_content = re.sub(download_pattern, replace_link, content)

    # Debug log to see if processing worked
    if processed_content != content:
        st.write(f"🔍 调试：已处理下载链接 - 共发现 {content.count('/api/download/report/')} 个链接")

    return processed_content


def render_content_with_downloads(content: str) -> None:
    """Render content and replace download placeholders with actual download buttons."""
    import re

    # Split content by download placeholders
    download_pattern = r"\[DOWNLOAD_LINK:([^)]+)\]"
    parts = re.split(download_pattern, content)

    for i, part in enumerate(parts):
        if i % 2 == 0:
            # Regular content
            if part.strip():
                st.markdown(part)
        else:
            # Download link filename
            filename = part
            file_content, mime_type = get_report_file_content(filename)

            if file_content is not None:
                st.download_button(
                    label=f"📥 下载 {filename}",
                    data=file_content,
                    file_name=filename,
                    mime=mime_type,
                    key=f"inline_download_{filename}_{hash(content)}",
                )
            else:
                st.error(f"❌ 无法加载报告：{filename}")


def display_message_with_thinking(
    role: str, content: str, thinking_steps: list[str] = None, plot_figure: go.Figure = None
):
    """Display a message with collapsible thinking section"""
    with st.chat_message(role):
        if thinking_steps and role == "assistant":
            # Create thinking section with all content inside
            with st.expander("💭 AI 思考过程", expanded=False):
                for i, step in enumerate(thinking_steps, 1):
                    st.markdown(f"**步骤 {i}：** {step}")

                if content:
                    st.markdown("**🤖 回答：**")
                    render_content_with_downloads(content)

                st.success("✅ 分析完成")

        # For non-assistant messages, display content normally
        elif content and role != "assistant":
            render_content_with_downloads(content)

        # Display plot if available (outside thinking container)
        if plot_figure:
            st.plotly_chart(plot_figure, width="stretch", key=str(uuid.uuid4()))


# Main UI
st.markdown(
    """
    <div class="header-title">📊 SmartBI Mate 智能数据分析</div>
    <div class="header-subtitle">用自然语言提问，AI 自动理解数据、生成 SQL、分析并可视化</div>
    """,
    unsafe_allow_html=True,
)

# Sidebar for configuration
with st.sidebar:
    st.header("⚙️ 会话配置")
    user_id = st.text_input("用户 ID", value="default", help="同一用户的会话标识")
    session_id = st.text_input("会话 ID", value="default", help="区分不同对话的会话标识")

    # Optional multi-provider support
    llm_provider = None
    provider_options = list_llm_providers()
    if provider_options:
        try:
            default_provider = getattr(smartbi_mate_config.get(), "llm_provider", None)
        except Exception:
            default_provider = None
        default_index = provider_options.index(default_provider) if default_provider in provider_options else 0
        llm_provider = st.selectbox(
            "LLM 模型",
            options=provider_options,
            index=default_index,
            help="选择本次会话使用的模型提供商",
        )

    st.markdown("---")
    st.markdown(
        """
    **💡 使用说明：**
    - 在下方输入您的业务问题（中文即可）
    - 可展开「AI 思考过程」查看每一步推理与 SQL
    - 图表生成后会在回答区展示
    - 不同会话 ID 之间互不干扰
    """
    )

    if st.button("🗑️ 清空对话"):
        st.session_state.messages = []
        st.rerun()

    st.markdown("---")
    st.markdown("### 📁 报告下载")

    # Get available reports
    available_reports = get_available_reports()

    if available_reports:
        selected_report = st.selectbox(
            "选择要下载的报告:", options=[""] + available_reports, help="选择要下载的报告文件"
        )

        if selected_report and st.button("📥 下载报告"):
            file_content, mime_type = get_report_file_content(selected_report)
            if file_content is not None:
                st.download_button(
                    label=f"💾 保存 {selected_report}",
                    data=file_content,
                    file_name=selected_report,
                    mime=mime_type,
                    key=f"download_{selected_report}",
                )
                st.success(f"✅ {selected_report} 已准备好，可下载！")
    else:
        st.info("暂无可下载的报告。")

# Restore persisted history from the checkpointer when the active thread changes
# (e.g. page refresh or switching User/Session ID). No-op within the same thread.
restore_history_if_needed(user_id, session_id, llm_provider)

# Display chat history
for msg in st.session_state.messages:
    if msg["type"] == "chronological_message":
        # Display chronological content in expander - all collapsed after completion
        with st.chat_message(msg["role"]):
            with st.expander("💭 AI 思考过程", expanded=False):
                st.markdown(msg["chronological_content"])

            # Extract and display final answer text outside thinking
            if msg.get("final_answer"):
                render_content_with_downloads(msg["final_answer"])

            # Display plot if available (outside thinking container)
            if msg.get("plot_figure"):
                st.plotly_chart(msg["plot_figure"], width="stretch", key=str(uuid.uuid4()))

    elif msg["type"] == "thinking_message":
        display_message_with_thinking(
            msg["role"], msg["content"], msg.get("thinking_steps", []), msg.get("plot_figure")
        )
    else:
        with st.chat_message(msg["role"]):
            if msg["type"] == "text":
                render_content_with_downloads(msg["content"])
            elif msg["type"] == "plot" and msg.get("plot_figure"):
                st.plotly_chart(msg["plot_figure"], width="stretch", key=str(uuid.uuid4()))

# Chat input
if prompt := st.chat_input("用自然语言向您的数据提问，例如：2024年6月华东区销售额是多少？"):
    # Add user message
    st.session_state.messages.append({"role": "user", "type": "text", "content": prompt})

    # Display user message immediately
    with st.chat_message("user"):
        st.markdown(prompt)

    # Process assistant response with real-time streaming
    with st.chat_message("assistant"):
        # Create thinking and response containers
        thinking_expander = st.expander("💭 AI 思考过程...", expanded=True)
        thinking_container = thinking_expander.container()
        response_container = st.container()

        # Process the message asynchronously with real-time updates
        try:
            # Reuse the same event loop to avoid binding issues
            if st.session_state.event_loop is None or st.session_state.event_loop.is_closed():
                st.session_state.event_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(st.session_state.event_loop)

            loop = st.session_state.event_loop
            final_response, plot_figure, thinking_steps, full_chronological_content, final_answer = (
                loop.run_until_complete(
                    process_user_message_stream(
                        prompt, user_id, session_id, llm_provider, thinking_container, response_container
                    )
                )
            )

            # No need to create another expander - content is already shown in real-time
            # Process download links in the content before storing
            processed_chronological_content = process_download_links(full_chronological_content)
            processed_final_answer = process_download_links(final_answer) if final_answer else final_answer

            # Store the complete message with the processed content
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "type": "chronological_message",
                    "chronological_content": processed_chronological_content,
                    "final_answer": processed_final_answer,
                    "plot_figure": plot_figure,
                }
            )

            # Trigger rerun to collapse the thinking section
            st.rerun()

        except Exception as e:
            traceback.print_exc()
            st.error(f"❌ 处理请求出错：{str(e)}")
            error_content = f"❌ Error: {str(e)}"
            processed_error_content = process_download_links(error_content)
            st.session_state.messages.append({"role": "assistant", "type": "text", "content": processed_error_content})


# Cleanup on session end
def cleanup_session():
    """Cleanup resources when session ends"""
    if "graph_manager" in st.session_state:
        try:
            # Use the same event loop for cleanup
            if st.session_state.event_loop and not st.session_state.event_loop.is_closed():
                loop = st.session_state.event_loop
                loop.run_until_complete(st.session_state.graph_manager.cleanup())
                loop.close()
                st.session_state.event_loop = None
        except Exception as e:
            log(f"Error during session cleanup: {e}")


# Register cleanup (this is a simplified approach - in production you might want more robust cleanup)

atexit.register(cleanup_session)

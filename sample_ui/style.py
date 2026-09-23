"""SmartBI Mate 自定义 UI 样式（中文 + 现代 BI 风格）"""

custom_css = """
<style>
/* ===== 全局 ===== */
html, body, [class*="css"] {
    font-family: "PingFang SC", "Microsoft YaHei", "Inter", "Helvetica Neue", sans-serif;
}

/* 隐藏 Streamlit 默认页脚，让界面更干净 */
footer {visibility: hidden;}
#MainMenu {visibility: hidden;}

/* ===== 顶部标题区 ===== */
.header-title {
    font-size: 26px;
    font-weight: 700;
    color: #1f2d3d;
    margin-bottom: 2px;
}
.header-subtitle {
    font-size: 14px;
    color: #6b7785;
    margin-bottom: 16px;
}

/* ===== 左侧配置面板 ===== */
.sidebar-section-title {
    font-size: 15px;
    font-weight: 600;
    color: #1f2d3d;
    margin: 8px 0 4px 0;
}

/* ===== 对话气泡 ===== */
.stChatMessage {
    border-radius: 12px !important;
}
.stChatMessage[data-testid="stChatMessage"]:has([data-testid="stChatMessageContent"].[class*="user"])
{ /* 用户气泡样式占位，配合下面覆盖 */
}
.user-msg {
    background: #e8f4ff;
    border-radius: 12px 12px 4px 12px;
    padding: 10px 14px;
    margin: 4px 0;
    font-size: 15px;
}
.assistant-msg {
    background: #ffffff;
    border-radius: 12px 12px 12px 4px;
    padding: 10px 14px;
    margin: 4px 0;
    font-size: 15px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

/* ===== 思考过程折叠区 ===== */
.stExpander {
    border: 1px solid #e5e9f0 !important;
    border-radius: 10px !important;
    background: #f8fafc !important;
    margin-bottom: 8px;
}
.stExpander details summary {
    font-size: 14px;
    font-weight: 600;
    color: #64748b;
}
.stExpander details[open] {
    background: #ffffff !important;
}

/* ===== 右下角可视化图表容器 ===== */
.visualization-panel {
    border: 1px solid #e5e9f0;
    border-radius: 12px;
    background: #ffffff;
    padding: 14px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.visualization-panel-title {
    font-size: 14px;
    font-weight: 600;
    color: #334155;
    margin-bottom: 8px;
}
</style>
"""
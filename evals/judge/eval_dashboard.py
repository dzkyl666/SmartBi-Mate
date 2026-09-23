"""SmartBI Mate 评测看板（Streamlit）。

读取 evals/judge/run_judge.py 产出的 report.json，展示 Text2SQL 评测结果：
- 总览指标：通过率、平均分、评估/跳过数
- 分类聚合：按 category 的通过率与均分（表格 + 柱状图）
- 逐用例明细：每个用例的分数、通过状态、评分理由

用法：
    python -m streamlit run evals/judge/eval_dashboard.py --server.port=8502

需要先跑完评测链路：
    python -m evals.judge.collect_generated --cases evals/judge/mysql_cases --config config/config.yaml --out judge_out/generated.json
    python -m evals.judge.run_judge --cases evals/judge/mysql_cases --config config/config.yaml --generated judge_out/generated.json --out judge_out/report.json
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="SmartBI Mate - 评测看板", page_icon="📊", layout="wide")

try:
    from sample_ui.style import custom_css
    st.markdown(custom_css, unsafe_allow_html=True)
except Exception:
    pass

DEFAULT_REPORT = "judge_out/report.json"


# --------------------------------------------------------------------------- #
# 数据加载
# --------------------------------------------------------------------------- #
def load_report(path: str) -> dict | None:
    """读取评测报告 JSON，返回 dict；文件不存在或解析失败返回 None。"""
    p = Path(path)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        st.error(f"报告解析失败：{e}")
        return None


def report_to_dataframes(report: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """把报告转成两个 DataFrame：分类聚合表 + 用例明细表。"""
    by_category = report.get("by_category", {})
    cat_rows = []
    for cat, bucket in sorted(by_category.items()):
        cat_rows.append(
            {
                "分类": cat,
                "用例数": bucket.get("total", 0),
                "评估数": bucket.get("evaluated", 0),
                "跳过数": bucket.get("skipped", 0),
                "通过数": bucket.get("passed", 0),
                "通过率": bucket.get("pass_rate", 0.0),
                "平均分": bucket.get("mean_score", 0.0),
            }
        )
    cat_df = pd.DataFrame(cat_rows) if cat_rows else pd.DataFrame(
        columns=["分类", "用例数", "评估数", "跳过数", "通过数", "通过率", "平均分"]
    )

    cases = report.get("cases", [])
    case_rows = []
    for c in cases:
        case_rows.append(
            {
                "用例ID": c.get("id", ""),
                "分类": c.get("category", "未分类"),
                "分数": c.get("score"),
                "通过": "✅" if c.get("passed") else ("⏭️" if c.get("skipped") else "❌"),
                "跳过原因": c.get("skip_reason", ""),
                "评分理由": c.get("reasoning", ""),
            }
        )
    case_df = pd.DataFrame(case_rows) if case_rows else pd.DataFrame(
        columns=["用例ID", "分类", "分数", "通过", "跳过原因", "评分理由"]
    )
    return cat_df, case_df


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #
def render_overview(report: dict) -> None:
    """总览指标卡。"""
    overall = report.get("overall", {})
    progress = report.get("progress", {})

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("总通过率", f"{overall.get('pass_rate', 0.0) * 100:.1f}%")
    c2.metric("平均分", f"{overall.get('mean_score', 0.0):.2f}")
    c3.metric("已评估", f"{overall.get('evaluated', 0)}")
    c4.metric("跳过", f"{overall.get('skipped', 0)}")
    c5.metric("处理进度", f"{progress.get('processed', 0)}/{progress.get('total', 0)}")

    mode = report.get("mode", "?")
    st.caption(f"评测模式：`{mode}`（smoke = 金标准自评，仅验证链路；generated = 真实 agent 生成对比）")


def render_category(cat_df: pd.DataFrame) -> None:
    """分类聚合：表格 + 柱状图。"""
    st.subheader("📂 按分类聚合")
    if cat_df.empty:
        st.info("暂无分类数据。")
        return

    left, right = st.columns([3, 2])
    with left:
        st.dataframe(
            cat_df.assign(通过率=cat_df["通过率"] * 100).round(2).style.format(
                {"平均分": "{:.3f}"}
            ),
            width="stretch",
            hide_index=True,
        )
    with right:
        fig = px.bar(
            cat_df.sort_values("通过率", ascending=True),
            x="通过率",
            y="分类",
            orientation="h",
            title="各分类通过率",
            text=cat_df["通过率"].map(lambda v: f"{v * 100:.0f}%"),
            color="通过率",
            color_continuous_scale="Blues",
        )
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch", key=f"cat_bar_{uuid.uuid4()}")


def render_cases(case_df: pd.DataFrame, report_path: str) -> None:
    """逐用例明细。"""
    st.subheader("🔍 逐用例明细")
    if case_df.empty:
        st.info("暂无用例数据。")
        return

    # 过滤条件
    col1, col2 = st.columns([1, 2])
    with col1:
        status_filter = st.selectbox("按结果过滤", ["全部", "通过", "失败", "跳过"], key="status_filter")
    with col2:
        search = st.text_input("搜索用例 ID / 分类", "", key="case_search")

    df = case_df.copy()
    if status_filter == "通过":
        df = df[df["通过"] == "✅"]
    elif status_filter == "失败":
        df = df[df["通过"] == "❌"]
    elif status_filter == "跳过":
        df = df[df["通过"] == "⏭️"]
    if search:
        df = df[df["用例ID"].str.contains(search, case=False) | df["分类"].str.contains(search, case=False)]

    st.dataframe(df, width="stretch", hide_index=True)

    # 单例详情
    with st.expander("📄 查看单个用例的完整评分理由", expanded=False):
        case_ids = case_df["用例ID"].tolist()
        selected = st.selectbox("选择用例", case_ids, key="case_select")
        if selected:
            row = case_df[case_df["用例ID"] == selected].iloc[0]
            st.markdown(f"**用例：** `{selected}`　**分类：** {row['分类']}　**分数：** {row['分数']}　**结果：** {row['通过']}")
            if row["跳过原因"]:
                st.warning(f"跳过原因：{row['跳过原因']}")
            st.markdown("**评分理由：**")
            st.markdown(row["评分理由"] if row["评分理由"] else "（无）")

    if report_path:
        st.caption(f"数据来源：`{report_path}`")


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def main() -> None:
    st.markdown(
        """
        <div class="header-title">📊 SmartBI Mate 评测看板</div>
        <div class="header-subtitle">LLM-as-Judge 评测 Text2SQL 生成质量：通过率、分类表现、逐用例明细</div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("⚙️ 报告设置")
        report_path = st.text_input("报告文件路径", value=DEFAULT_REPORT, help="run_judge 产出的 report.json 路径")
        if st.button("🔄 重新加载"):
            st.rerun()
        st.markdown("---")
        st.markdown(
            """
        **💡 评测流程**
        1. `collect_generated`：真实 agent 逐题生成 SQL
        2. `run_judge`：LLM 对比生成的 SQL 与金标准 SQL 打分
        3. 看板读取 `report.json` 展示结果
        """
        )
        st.markdown("---")
        st.markdown("**📁 评测用例** `evals/judge/mysql_cases/`（10 例，针对电商库 4 张表）")

    report = load_report(report_path)
    if report is None:
        st.warning(
            f"未找到报告文件 `{report_path}`。\n\n"
            "请先运行评测链路：\n\n"
            "```bash\n"
            "python -m evals.judge.collect_generated --cases evals/judge/mysql_cases "
            "--config config/config.yaml --out judge_out/generated.json\n"
            "python -m evals.judge.run_judge --cases evals/judge/mysql_cases "
            "--config config/config.yaml --generated judge_out/generated.json --out judge_out/report.json\n"
            "```"
        )
        return

    render_overview(report)
    st.divider()
    cat_df, case_df = report_to_dataframes(report)
    render_category(cat_df)
    st.divider()
    render_cases(case_df, report_path)


if __name__ == "__main__":
    main()
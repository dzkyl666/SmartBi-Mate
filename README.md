# SmartBI Mate

> **作者**：李永康（独立开发者）  
> **版权**：© 2024 李永康。本项目为个人学习/求职作品，所有代码均为本人独立编写。  
> **开源协议**：MIT License（见 LICENSE 文件）

用自然语言（中文）向你的数据库提问，AI 自动完成「理解问题 → 生成 SQL → 执行 → 可视化」全流程的智能数据分析助理。

聚焦国内落地：百炼 DashScope 大模型 + MySQL + 全中文对话，去掉 Trino/Docker/Gradio/MCP 等重依赖，只保留一条最精简、可跑通、可讲清的链路。

---

## 一、项目是什么

我给你一个电商数据库（4 张表），你可以直接用中文问：

```
「2024年6月华东区销售额是多少」
「各品类2024年销售额排名」
「客单价最高的前5个用户」
「数码品类6月和7月的销售额环比增长率」
「2024年各地区每月销售额趋势」
```

系统会经历 **5 步**，自动给出答案 + 图表：

```
你的问题
   │
   ▼
① 信息抽取      LLM 从问题里抽出「维度 / 指标 / 时间 / 过滤条件」
   ▼
② 表选择       在 4 张表里挑出需要的表 + 列（向量检索 + LLM）
   ▼
③ SQL 生成     根据已选表 + 少样本示例，生成 MySQL 语句
   ▼
④ SQL 执行     在真实 MySQL 上跑（只读守卫 + 结果条数限制）
   ▼
⑤ 置信度闸门    LLM 给 SQL 打分，低于阈值时弹窗请人工确认（HITL）
   ▼
可视化 + 答案   Plotly 图表 + 中文结论
```

---

## 二、技术架构

```
┌─────────────────────────────────────────────────────────┐
│                    展示层（Streamlit）                      │
│   sample_ui/streamlit_ui.py  — 对话流 + 思考过程折叠         │
│   evals/judge/eval_dashboard.py — 评测看板                 │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                  Agent 编排层（LangGraph）                 │
│   agent_graph.py  — 主图（llm_node / use_tool / ask_human）│
│   text2sql/sql_graph.py — SQL 子图（5 步流水线）            │
└───────────┬───────────────────────────────┬──────────────┘
            │                               │
┌───────────▼──────────────┐   ┌────────────▼─────────────┐
│      LLM（百炼 DashScope）  │   │    NLP / 检索            │
│  qwen3-max（对话/生成）      │   │  text-embedding-v4（向量）│
│  text-embedding-v4（embed） │   │  BM25 + 编辑距离（兜底）  │
└───────────┬──────────────┘   └────────────┬─────────────┘
            │                               │
            ▼                               ▼
┌─────────────────────────┐   ┌──────────────────────────┐
│   MySQL（insightbi_demo） │   │   Catalog（表元数据）       │
│  dim_region / dim_product │   │  config/catalog/*.yaml    │
│  dim_user / fact_order    │   │  术语表 + 表说明 + SQL 示例 │
│  （4 张中文电商表，124 订单）│   └──────────────────────────┘
└─────────────────────────┘
```

**核心依赖**：`langgraph`（图编排）+ `langchain-openai`（LLM 接入）+ `streamlit`（UI）+ `pymysql`（数据库）+ `chromadb`（向量检索）。

---

## 三、目录结构

```
SmartBi Mate/
├── run_cli.py                  # CLI 入口（无界面跑一次完整链路）
├── run_streamlit_ui.py         # Web UI 入口
├── config/
│   ├── config.yaml             # 主配置（模型/数据库/闸门）
│   └── catalog/                # 业务知识库
│       ├── bi.yaml             # 术语表 + 选表/SQL 规则（含数据时间范围）
│       ├── table_info.yaml     # 4 张表的描述 + selection_rule + sql_rule
│       ├── table_columns.csv   # 列级元数据（向量检索原料）
│       ├── common_columns.csv
│       ├── sql_example.yaml    # Q→SQL 少样本示例
│       └── table_selection_example.csv
├── smartbi_mate/                 # 核心代码
│   ├── agent_graph.py          # 主 Agent 图
│   ├── config_loader.py        # 配置加载（已改造）
│   ├── text2sql/               # SQL 子图（抽取/选表/生成/执行/评分）
│   ├── catalog/                # 元数据存储与检索（含懒加载）
│   ├── tool/                   # 工具（search_schema/text2sql/ask_human/...）
│   ├── llm/  prompts/  observability/
│   └── utils.py                # 工具函数（含 DashScope embedding wrapper）
├── sample_ui/                  # Streamlit 界面
│   ├── streamlit_ui.py         # 主界面（中文）
│   └── style.py                # 样式
├── evals/judge/                # LLM-as-Judge 评测
│   ├── mysql_cases/            # 针对电商库的 10 个评测用例
│   ├── collect_generated.py    # 步骤1：真实 agent 生成 SQL
│   ├── run_judge.py            # 步骤2：LLM 打分
│   └── eval_dashboard.py       # 评测看板
├── scripts/init_demo_data.sql  # 建库建表 + 灌入演示数据
├── judge_out/                  # 评测产物（generated.json / report.json）
└── requirements.txt
```

---

## 四、快速开始

### 0. 前置条件

- Python 3.11 + MySQL（本地 `127.0.0.1:3306`）
- 一个百炼 DashScope API Key（环境变量 `DASHSCOPE_API_KEY`）

### 1. 初始化数据

```bash
mysql -u root -p < scripts/init_demo_data.sql
```

建出 `insightbi_demo` 库的 4 张表：`dim_region`(20) / `dim_product`(24) / `dim_user`(20) / `fact_order`(124)。

### 2. 配置

编辑 `config/config.yaml`，把第 34 行 MySQL 连接改成你的账号密码：

```yaml
data_warehouse_config:
  uri: "mysql+pymysql://用户名:密码@127.0.0.1:3306/insightbi_demo?charset=utf8mb4"
```

API Key 用环境变量注入（不要写进 config）：

```powershell
$env:DASHSCOPE_API_KEY = "你的key"
```

### 3. 启动（两种方式任选）

**CLI 无界面（调试推荐）：**

```powershell
$env:CONFIG_FILE="config/config.yaml"
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe run_cli.py "2024年6月华东区销售额是多少"
```

**Web 界面：**

```powershell
$env:CONFIG_FILE="config/config.yaml"
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe run_streamlit_ui.py
```

浏览器打开 http://localhost:8501，在输入框用中文提问。

> **为什么要设这两个环境变量？**
> - `CONFIG_FILE`：程序默认找 `smartbi_mate/config.yaml`，实际在 `config/config.yaml`，不设会报「配置未加载」。
> - `PYTHONIOENCODING`：Windows 终端默认 GBK，中文 + emoji 输出会崩。

---

## 五、评测系统

用 LLM-as-Judge 客观衡量 Text2SQL 生成质量，配套一个可视化看板。

```powershell
# 步骤1：跑真实 agent，逐题生成 SQL
.\.venv\Scripts\python.exe -m evals.judge.collect_generated `
  --cases evals/judge/mysql_cases --config config/config.yaml --out judge_out/generated.json

# 步骤2：LLM 对比生成 SQL vs 金标准 SQL，打分
.\.venv\Scripts\python.exe -m evals.judge.run_judge `
  --cases evals/judge/mysql_cases --config config/config.yaml `
  --generated judge_out/generated.json --out judge_out/report.json

# 步骤3：看板展示
.\.venv\Scripts\python.exe -m streamlit run evals/judge/eval_dashboard.py --server.port=8502
```

**当前评测结果**（10 个用例，覆盖聚合/筛选/join/环比/TopN/趋势等）：

| 指标 | 值 |
|------|-----|
| 通过率 | 90%（9/10） |
| 平均分 | 0.89 |

唯一未通过的是「环比增长率」——agent 生成了 6/7 月各月销售额，但没算增长率百分比；这是当前能力边界，也是一个清晰的优化方向。

## 

---

## 六、核心设计决策

1. **Embedding 直接走 SDK**：绕开 langchain-openai 的 tokenize 兼容问题（见踩坑表）。
2. **Catalog 懒加载**：模块级单例改为首次访问才初始化，避开 import 时序问题。
3. **向量检索 + 规则兜底**：embedding 失败时靠 BM25 + 编辑距离继续跑，不让单点故障崩掉整条链路。
4. **http_client 仅注入 ChatOpenAI**：`trust_env=False` 防止走系统代理超时；embedding 不注入（会触发 tokenize bug）。
5. **HITL 置信度闸门**：SQL 执行后 LLM 打分，低于阈值弹窗请人工 approve/reject/edit，把「拍板权」留给用户。



---

## 七、开发历程

- [x] **阶段1**：项目架构设计 + 核心模块实现
- [x] **阶段2**：配置系统 + MySQL 数据源对接
- [x] **阶段3**：Text2SQL 核心链路打通（CLI Q1-Q5 全过）
- [x] **阶段4**：UI 中文化 + HITL 置信度闸门验证 + 评测看板
- [ ] 优化：环比等派生指标的 planning 层
- [ ] 截图补齐 + 架构 Mermaid 图
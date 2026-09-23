# SmartBI Mate 项目进度

> **本文件是进度的唯一权威来源**，每阶段由 AI 追加更新。

## 当前阶段

**Phase 4：UI + 评测已基本完成**，进入收尾/可选优化阶段

## 已完成

### Phase 1：项目骨架搭建 ✅
| # | 事项 | 备注 |
|---|------|------|
| 1 | 目录结构创建 + 核心模块整理 | 从上游项目提取必要模块并重构 |
| 2 | requirements.txt 生成 | 精简依赖，去掉 Trino/Docker/Gradio/MCP |
| 3 | .env.example 生成 | 只有变量名+中文注释 |
| 4 | .venv 创建 + pip install | Python 3.11.9，清华源 |
| 5 | `python -c "import openchatbi"` 通过 | 修复 helper.py token_service 引用 |

### Phase 2：配置 + 数据源打通 ✅
| # | 事项 | 备注 |
|---|------|------|
| 6 | scripts/init_demo_data.sql | 4张中文电商表，124条订单，金额自洽 |
| 7 | config/config.yaml | 百炼 qwen3-max + text-embedding-v4 + MySQL |
| 8 | config/catalog/ 6个文件 | bi.yaml / table_info.yaml / common_columns.csv / table_columns.csv / sql_example.yaml / table_selection_example.csv |
| 9 | config_loader.py 改造 | dialect默认mysql + trust_env=False + api_key环境变量注入 |
| 10 | MySQL 建表验证通过 | dim_region:20, dim_product:24, dim_user:20, fact_order:124, inconsistent:0 |

### Phase 3：核心链路调通 ✅（Q1-Q5 全部通过）
| # | 事项 | 备注 |
|---|------|------|
| 11 | agent_graph.py 改造 | 删 analysis/MCP 引用，工具描述中文化 |
| 12 | run_python_code.py 精简 | 只保留 LocalExecutor |
| 13 | DashScope Embedding Wrapper | 绕过 langchain-openai tokenize bug |
| 14 | schema_retrival.py 懒加载 | 解决模块导入时 config 未加载导致 mapping 为空 |
| 15 | table_info.yaml 格式修复 | 改为 `'': { table_name: {...} }` 嵌套格式 |
| 16 | sql_dialect 包重建 | __init__.py + mysql.md |
| 17 | system_prompt.py UTF-8 修复 | 所有 .open() 加 encoding="utf-8" |
| 18 | **CLI Q1 测试通过** | "2024年6月华东区销售额" → 7,719.85元，置信度1.00 |
| 19 | **CLI Q2 测试通过** | "各品类销售额排名" → 数码82872.65/美妆17872.40/…，用量与SQL全对上（pay_amount+已完成口径） |
| 20 | **CLI Q3 测试通过** | "客单价top5" → 3087.63/3005.92/2400.26/2113.48/1938.78，数字全对（唯缺username） |
| 21 | **CLI Q4 测试通过** | "数码6/7月环比" → 6月11202.53、7月8996.05、环比-19.70%，全对 |
| 22 | **CLI Q5 测试通过** | "地区×月份趋势" ✅ 修复 embedding 兜底后通过，1轮直达，置信度1.00 |
| 23 | **遗留问题修复并验证** | 时间歧义（bi.yaml 加数据时间范围）+ username（glossary 加 JOIN dim_user 规则），Q3 重测通过 |
| 24 | **UI 中文化完成** | streamlit_ui.py 全部界面文案中文化 + style.py 重写（现代 BI 风格）+ run_streamlit_ui.py 入口中文 |
| 25 | **HITL 可视化验证通过** | 阈值临时调 1.01 触发闸门：interrupt 弹窗正常，approve→继续出结果(840.00正确)，reject→重新生成SQL；验证完阈值已还原 0.7。发现：reject 重生成 SQL 月份可能漂移(12→11)，靠再次 HITL 兜住 |
| 26 | **eval_dashboard.py 评测看板完成** | 建了 evals/judge/mysql_cases/ 10个电商库评测用例 + 看板（总览指标/分类聚合/逐用例明细）。实跑评测：通过率90%(9/10)、平均分0.89；唯一挂的是"环比增长率"（agent 只算了各月销售额没算增长率百分比） |
| 27 | **README.md 完成** | 架构图（文字版）+ 目录结构 + 快速开始 + 评测系统 + 踩坑记录 + 核心设计决策 + 面试讲法 + 迭代路线 |
| 28 | **中文可视化验证通过** | 问"2024年各月销售额趋势"→ 出 Plotly 折线图（1-12月，6/11月大促双高峰清晰，数据准确）。确认走的是"时间列+数值列→LINE"数据特征规则，非关键词，中文场景不踩英文关键词坑 |
| 29 | **深度分析-派生指标修复** | bi.yaml glossary 加"派生指标 SQL 生成铁律"(环比/同比/占比必须一步算完，禁止只查原始值)；修正 sql_example.yaml 里环比示例(case when 分子方向反了)。评测通过率 90%→100%，环比题 ex_mysql_04 从 0 分变 1.000 满分 |
| 30 | **模型切换到 qwen3.7-flash** | config.yaml default_llm.model 从 qwen3-max 改为 qwen3.7-flash（实测 qwen3-flash 不存在 404，正确名是 qwen3.7-flash，带 reasoning 的新架构）。冒烟通过："2024年6月华东区销售额→7719.85" 全对 |
| 31 | **稳定生成报告打通** | save_report 工具描述中文化+触发约定强化 + agent_prompt 加报告行为规则。实测问"整理成报告"→ 正确触发 save_report，落盘 data/reports/*.md + 返回下载链接 |
| 32 | **长期记忆打通** | config.yaml 加 memory_config 段：enable_pattern_memory=true + enable_memory_decay_rerank=true。验证 get_memory_config 读到 true，且查询日志出现"Blended examples (store)"= 从 learned store 检索注入历史 SQL 模式生效 |

## 进行中

- [x] Phase 4：UI 中文化 + style.py 重写 ✅（见 #24）
- [x] Phase 4：HITL 可视化验证 ✅（见 #25）
- [x] Phase 4：eval_dashboard.py 评测看板 ✅（见 #26）
- [x] README.md ✅（见 #27）

## 待做（后续可选优化）

- [ ] 环比等「跨行计算」派生指标的 planning 层（评测暴露的能力边界，见 README 第八节）
- [ ] 三区布局（如需硬拆三列；当前侧边栏+对话流方案已够用）
- [ ] README 补演示截图 + 架构 Mermaid 图

## 已知问题 / 已解决

| 问题 | 状态 | 解决方案 |
|------|------|----------|
| mcp_tools / analysis.agent 导入失败 | ✅ 已解决 | 从 agent_graph.py 删除 |
| 百炼 Embedding API token IDs 错误 | ✅ 已解决 | _DashScopeEmbeddingWrapper 绕过 tokenize |
| column_tables_mapping 为空 | ✅ 已解决 | schema_retrival.py 懒加载 _LazyProxy |
| get_table_information() 返回空 | ✅ 已解决 | table_info.yaml 加 db_name 嵌套层 |
| sql_dialect 包缺失 | ✅ 已解决 | 重建 __init__.py + mysql.md |
| prompt 文件 GBK 编码错误 | ✅ 已解决 | 所有 .open() 加 encoding="utf-8" |
| CLI 输出 emoji GBK 错误 | ✅ 已解决 | PYTHONIOENCODING=utf-8 |
| DASHSCOPE_API_KEY 子进程不可见 | ✅ 已解决 | config_loader 读注册表 fallback |
| text-embedding-v4 端点间歇性 400 | ✅ 已解决 | column_retrieval 加重试+降级空列表，_DashScopeEmbeddingWrapper 加重试 |
| 时间基准错位（今年=2026） | ✅ 已解决 | bi.yaml glossary 加"数据时间范围 2024"，LLM 遇相对时间对齐到 2024，消除空转 |
| Q3 结果缺 username | ✅ 已解决 | bi.yaml glossary 加"涉及用户必 JOIN dim_user 返回 user_name"，重测通过 |

## 关键技术决策记录

1. **Embedding**: langchain-openai 1.6.x 的 OpenAIEmbeddings 与百炼不兼容（tokenize 后发 int 列表），用 `_DashScopeEmbeddingWrapper` 直接调 openai SDK
2. **Catalog 懒加载**: `schema_retrival.py` 模块级变量在 import 时 config 未加载，改为 `_LazyProxy` 首次访问时初始化
3. **table_info.yaml 格式**: FileSystemCatalogStore 要求 `{db_name: {table_name: {...}}}` 嵌套结构，空 db_name 用 `''` 作 key
4. **http_client 注入**: 只对 ChatOpenAI 注入 `trust_env=False`；OpenAIEmbeddings 不注入（会触发 tokenize bug）

## 下一步接续指引

新对话开始时：
1. 读本文件确认进度
2. 主线（Phase 1~4）已全部完成：骨架 / 数据打通 / 核心链路(CLI Q1-Q5) / UI中文化 / HITL验证 / 评测看板 / README
3. 剩余为可选优化项（见「待做」）：
   - 环比等「跨行计算」派生指标的 planning 层（评测暴露的能力边界）
   - 三区布局（如需）
   - README 补截图 + Mermaid 架构图

# 2026-02-03 PRD 合并对齐（v0.1 + multipage addendum）

## Goal / Acceptance Criteria

- 将 `docs/prd/value-pilot-prd-v0.1.md` 与 `docs/prd/value-pilot-prd-v0.1-multipage.md` 合并为 **单一的、持续更新的 v0.1 PRD 入口**（以 `value-pilot-prd-v0.1.md` 为准）。
- 在合并后的 PRD 中明确“契约源头/权威文档”：
  - v0.1 执行/数据契约以 `docs/prd/value-pilot-prd-v0.1.md` 为主；
  - `metric_key`/单位/period 语义与落库 mapping 以 `docs/metric_facts_mapping_spec.yml` 为准。
- 在存在不一致时，**必须**应用如下优先级（precedence）顺序：
  1. `docs/metric_facts_mapping_spec.yml`（metric 语义、metric_key/unit/period 相关契约）
  2. `docs/prd/value-pilot-prd-v0.1.md`（v0.1 执行/数据契约主入口）
  3. 历史 addendum / decision records（只读参考，不再作为权威来源）
- 消除当前 PRD 与代码的显式冲突：
  - 纠正 `metric_key` 命名约束（从 snake_case-only → dotted namespace + snake_case 的实际实现）。
  - 纠正 Value Line ingestion 范围（单页 → 支持多页 container，每页独立解析）并保留 `page_reports[]`/`parsed_partial` 等契约。
- 对 `docs/prd/value-pilot-prd-v0.1-multipage.md` 做“归档/重定向说明”，避免后续继续产生双源分叉（保留历史内容但标注已合并）。

## Scope

### In Scope
- 仅文档变更（PRD 合并、增补章节、澄清契约源头、过时内容标注）。
- 新增 `docs/prd/README.md`（可选）用于说明 PRD 目录内文件的关系、权威顺序、更新规则。

### Out of Scope
- 本任务 **不得**引入任何运行时行为变化；仅对齐文档与既有实现。
- 任何后端/前端代码修改
- Schema / migration 修改
- 新功能 PRD（例如股票池/实时行情的详细 PRD 另起任务）

## PRD / Contract References
- `docs/prd/value-pilot-prd-v0.1.md`
- `docs/prd/value-pilot-prd-v0.1-multipage.md`
- `docs/metric_facts_mapping_spec.yml`
- `docs/tasks/2026-01-21_metric-facts-mapping-spec.md`（metric_key 命名决策记录）

## Files To Change
- `docs/prd/value-pilot-prd-v0.1.md`
- `docs/prd/value-pilot-prd-v0.1-multipage.md`
- `docs/prd/README.md`（新增，可选）

## Test Plan (Docker)
- Docs-only 变更：不要求跑全量测试。
-（可选）`docker compose exec api pytest -q`（烟雾测试，确认无意外破坏仓库约定）

## Execution Plan (Needs Human Approval)
1) 在 `value-pilot-prd-v0.1.md` 增加 “Contract Sources / Naming Conventions” 小节，明确：
   - `metric_key` 允许 dotted namespace（与 `docs/metric_facts_mapping_spec.yml` 对齐）
   - mapping spec 为 metric_facts 落库的权威来源
2a) 将 `value-pilot-prd-v0.1-multipage.md` 的**语义模型**合并进 `value-pilot-prd-v0.1.md`：
   - multi-page container 定义
   - `parse_status` 语义（含 `parsed_partial`）
2b) 将 `value-pilot-prd-v0.1-multipage.md` 的**接口/输出契约**合并进 `value-pilot-prd-v0.1.md`：
   - `pdf_documents.stock_id` 规则
   - upload API `page_reports[]` schema 与必填约束
   - 在 PRD 中引用一个“非规范性（non-normative）”最小示例来源（不在 PRD 里重写 schema），例如单测 `backend/tests/unit/test_multipage_value_line_upload.py`
3) 在 `value-pilot-prd-v0.1-multipage.md` 顶部添加“已合并/冻结”说明（保留原文作为历史记录）。
4)（可选）新增 `docs/prd/README.md`，明确：
   - 哪个 PRD 是唯一入口
   - addendum/decision record 的使用方式
   - 禁止在 mapping spec 之外重新定义 metric 语义：任何新的 PRD/addendum 不得在 `docs/metric_facts_mapping_spec.yml` 之外重新定义 metric 语义（metric_key/unit/period 等）
5) 最小一致性检查：
   - repo 内搜索旧的 snake_case-only/field_map 叙述，并在 PRD 中做“deprecated/redirect”说明（不改代码）。
6) Definition of Done
   - 合并后的 `docs/prd/value-pilot-prd-v0.1.md` 中不再存在任何与 multipage 能力或 `metric_key` 命名（dotted namespace）相冲突的描述
   - repo 内不再存在把 `docs/prd/value-pilot-prd-v0.1-multipage.md` 当作“当前规范/权威来源”的引用（允许作为历史只读引用）

## Rollback Strategy
- 通过 git 回滚 `docs/prd/*` 与本任务文件的提交（或恢复到合并前的两份 PRD 状态）。
- 当 reviewer 认为“契约优先级/语义”产生新的歧义或存在多种可解释路径时，触发 rollback（语义失败也可回滚）。

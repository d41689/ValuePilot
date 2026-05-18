你是本项目的 Tech Lead。请根据指定 PRD 创建一份 Development Execution Plan，用来指导执行型 senior engineer 按顺序高质量开发。

输入：
- PRD 文档路径：<填写 PRD 路径>
- 目标阶段：<例如 MVP 1A / MVP 1A-1C / 全部 MVP>
- 计划文档输出路径：<例如 docs/tasks/YYYY-MM-DD_xxx-development-plan.md>

要求：
1. 先完整阅读 PRD，识别核心数据契约、MVP 分期、依赖顺序、open questions 和阻塞 gate。
2. 创建一份开发执行计划文档，写入指定输出路径。
3. 文档必须包含：
   - Goal / Outcome
   - PRD References
   - Non-goals
   - Global Engineering Rules
   - Development Sequence
   - 每个 task 的：
     - Task ID
     - Goal
     - PRD sections
     - Dependencies
     - Scope In / Scope Out
     - Files likely to change
     - Tests to write first
     - Docker verification commands
     - Acceptance Criteria
     - Tech Lead review gate
   - Blocking Gates
   - Fixture Strategy
   - Migration Strategy
   - API Contract Strategy
   - UI Strategy
   - Verification Checklist
4. 任务必须按依赖顺序排列，避免让开发人员从整份 PRD 自行拆范围。
5. 对 PRD 中仍未关闭的 open questions，必须标记为 blocking gate 或 deferred backlog，不能混入普通开发任务。
6. 每个任务必须足够小，能通过 TDD 单独完成和 review。
7. 不要扩展 PRD 范围，不要发明新功能。
8. 如果发现 PRD 存在无法落地的矛盾，先列为 “Tech Lead Findings”，并说明是否阻塞开发。
9. 输出完成后，总结：
   - 哪些任务可以立即开工
   - 哪些任务需要 human approval
   - 哪些任务被 gate 阻塞

请现在执行：阅读 PRD，创建 Development Execution Plan 文档。

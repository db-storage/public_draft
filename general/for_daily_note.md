
# Personal Work Notes with Git, Markdown & AI Agents

<!--
@type: personal-workflow
@status: proposed
@version: 1.0
@updated: 2026-11-12
@tags: [markdown, git, kiro, agents, tasks, daily-notes]
-->

## 1. Background & Goals

### 1.1 Background

日常工作需要记录：

- Todo：待完成任务、优先级、进度。
- Daily Notes：每日工作计划、进展、问题和思考。
- Meeting Notes：会议讨论、决策、Action Items。
- Knowledge：工作中积累的知识、经验和结论。

之前使用 Wiki，每天复制前一天的笔记：
- 删除已完成的 Todo。
- 保留未完成的 Todo。
- 增加当天的新任务及会议记录。

这种方式简单，但存在问题：

1. Todo 每天重复，缺少稳定身份。
2. 难以跟踪任务从创建到完成的历史。
3. 会议 Action Items 容易遗漏或重复。
4. 工作记录与相关设计文档不容易建立关联。
5. AI Agent 需要反复阅读历史笔记，消耗 Token。

### 1.2 Goals

1. 使用 Git + Markdown 统一管理个人工作记录。
2. 保留按天记录、查看工作的习惯。
3. Todo 自动跨天延续，不再手动复制。
4. 会议 Action Items 能够进入统一任务列表。
5. 利用 Kiro Agent 自动整理、总结、规划日常工作。
6. 支持任务、会议、设计文档之间的关联。
7. 尽量减少 Agent Token 消耗。
8. 保持简单，不引入复杂任务管理系统。

## 2. Core Principles

- **Git as Storage**：使用私有 Git Repository 存储个人笔记。
- **Markdown First**：所有内容使用普通 Markdown。
- **Single Source of Truth**：Todo 的当前状态只在一个位置维护。
- **Separate Tasks from Daily Logs**：任务和每天的日志分离。
- **Daily Notes as History**：Daily Notes 记录每天做了什么。
- **Stable Task Identity**：必要时使用 Task ID 跨天追踪任务。
- **Directory-Level Agent Rules**：不同目录使用自己的 `AGENTS.md`。
- **Progressive Context Loading**：Agent 只读取当前任务需要的内容。
- **Agent-Assisted, Human-Controlled**：Agent 辅助整理，不擅自修改重要结论。

## 3. Recommended Repository Structure

```text
work-notes/
├── README.md
├── AGENTS.md
│
├── tasks/
│   ├── AGENTS.md
│   ├── active.md
│   └── completed.md
│
├── daily/
│   ├── AGENTS.md
│   └── 2026/
│       └── 11/
│           ├── 2026-11-11.md
│           └── 2026-11-12.md
│
├── meetings/
│   ├── AGENTS.md
│   ├── 2026-11-11-design-review.md
│   └── 2026-11-12-team-sync.md
│
├── knowledge/
│   ├── AGENTS.md
│   └── temporal-auth.md
│
└── .kiro/
    ├── steering/
    │   └── global.md
    └── skills/
        ├── daily-planning/
        ├── meeting-processing/
        └── daily-wrapup/
```

目录职责：

| Directory | Responsibility |
|---|---|
| `tasks/` | 当前任务和已完成任务 |
| `daily/` | 每日工作记录 |
| `meetings/` | 会议纪要、决策、Action Items |
| `knowledge/` | 长期有效的知识和结论 |
| `AGENTS.md` | Agent 工作规则 |
| `.kiro/steering/` | Kiro 专用规则 |
| `.kiro/skills/` | 可复用的 Agent 工作流 |

建议使用独立的私有 Repository，不要直接将全部个人记录放到团队共享设计仓库。

## 4. Task Management

### 4.1 Single Source of Truth

所有未完成任务统一保存在：

`tasks/active.md`

每天不再复制前一天的 Todo。

任务未完成时，继续保留在 `active.md` 中；完成后再归档。

### 4.2 Active Tasks Example

```markdown
# Active Tasks

## High Priority

- [ ] Complete Temporal Authentication Design
  - ID: task-a83f21
  - Due: 2026-11-14
  - Status: in-progress
  - Related: docs/adr/003-identity-model.md

- [ ] Review Workflow Authentication Contract
  - ID: task-b71c82
  - Status: todo

## Normal Priority

- [ ] Investigate SPIRE JWT-SVID validation
  - ID: task-c92d13
  - Status: todo
```

建议：

- 每个 Todo 使用 Markdown Checkbox。
- 重要任务可以增加 ID。
- 截止日期、优先级按需填写。
- 不必为所有简单任务添加复杂 Metadata。
- 任务描述尽量具体、可执行。

### 4.3 Task Lifecycle

推荐状态：

| Status | Meaning |
|---|---|
| `todo` | 尚未开始 |
| `in-progress` | 正在推进 |
| `blocked` | 被外部条件阻塞 |
| `done` | 已完成 |
| `cancelled` | 已取消 |

简单任务只使用 `[ ]` 和 `[x]` 即可。

复杂任务再增加 Status。

避免 Checkbox 和 Status 出现矛盾。

### 4.4 Task Carryover

传统模式：

```text
Day 1 Todo
    ↓ Copy
Day 2 Todo
    ↓ Copy
Day 3 Todo
```

推荐模式：

```text
tasks/active.md
    ↑
    ├── Day 1 references tasks
    ├── Day 2 references tasks
    └── Day 3 references tasks
```

核心规则：

- 未完成任务持续保留在 `active.md`。
- Daily Notes 只引用任务，不复制完整任务状态。
- 任务完成后，从 `active.md` 移到 `completed.md`。
- Daily Notes 中保留当天的任务计划和历史进展。

完成任务时应保留创建日期、完成日期等有价值的信息。

## 5. Daily Notes

### 5.1 Purpose

Daily Notes 主要记录：

1. Today's Focus
2. Meetings
3. Progress
4. New Tasks
5. Blockers
6. Notes / Learnings

Daily Notes 是历史记录，而不是长期维护的 Todo 数据库。

### 5.2 Daily Note Example

文件：`daily/2026/11/2026-11-12.md`

```markdown
# 2026-11-12

## Today's Focus

- task-a83f21: Complete Temporal Auth Design
- task-b71c82: Review Workflow Contract

## Meetings

- 10:00 Auth Design Review
- 14:00 Team Sync

## Progress

### task-a83f21

- 确认 Human / Workload 分离方案。
- 下一步完善故障隔离设计。

## New Tasks

- 调研 SPIRE JWT-SVID 缓存策略。

## Blockers

- 等待 Frontend Team 确认接口。

## Notes

今天发现 ClaimMapper 需要重新设计。
```

### 5.3 Daily Notes Rules

- 每天一个 Markdown 文件。
- 文件名使用 `YYYY-MM-DD.md`。
- 记录事实、进展、决策和问题。
- 不反复复制所有未完成 Todo。
- 新任务应同步进入 `tasks/active.md`。
- Daily Notes 保留历史记录，原则上避免事后大幅重写。
- 允许补充遗漏信息，但应避免改变原始事实。

### 5.4 Daily Task Snapshot

如果希望像 Wiki 一样，每天都看到完整的待办列表，可以让 Agent 自动生成当天的任务快照。

例如：

```markdown
## Today's Todo

- [ ] task-a83f21: Complete Temporal Auth Design
- [ ] task-b71c82: Review Workflow Contract
```

注意：

- 快照用于阅读和规划。
- `tasks/active.md` 仍然是任务状态的权威来源。
- 不要把 Daily Snapshot 当作另一份独立任务列表。
- 如果在 Daily Note 中勾选任务，需要同步更新 `active.md`。
- 最简单的做法是 Daily Note 只使用任务引用，不通过勾选快照改变状态。

## 6. Meeting Notes

### 6.1 Meeting Note Structure

建议：

```markdown
# Auth Design Review

Date: 2026-11-12

## Participants

- Auth Team
- Workflow Team

## Topics

- Human / Workload authentication separation
- ClaimMapper design

## Decisions

- Human 使用 OIDC。
- Workload 使用 SPIFFE 身份。

## Action Items

- [ ] Update Auth Design
  - Owner: Auth Team

- [ ] Review Frontend ClaimMapper
  - Owner: Workflow Team

## Open Questions

- 两种认证路径的故障隔离如何实现？
```

### 6.2 Meeting Processing

会后可以让 Agent：

1. 提取 Decisions。
2. 提取 Action Items。
3. 识别 Open Questions。
4. 与 `tasks/active.md` 中的现有任务去重。
5. 为新任务创建 Todo。
6. 对已有任务补充进展或关联。
7. 不擅自修改原始会议决策。

会议记录是信息来源，`active.md` 是个人任务状态的来源。

对于分配给其他人的 Action Items，不应默认加入自己的个人任务列表；可以单独记录 Follow-up，或仅保留在会议纪要中。

## 7. Knowledge Management

### 7.1 Purpose

`knowledge/` 存储长期有效的知识：

- 技术研究。
- 设计原则。
- 问题排查经验。
- 重要总结。
- 可复用的工作方法。

### 7.2 Relationship with Daily Notes

Daily Notes：

> 今天发现 JWT Audience 需要分别校验。

Knowledge Note：

> JWT Audience 校验的背景、推荐方案和注意事项。

两者的区别：

| Daily Notes | Knowledge |
|---|---|
| 时间导向 | 主题导向 |
| 记录当天发生的事情 | 保存长期有效的结论 |
| 可能包含临时信息 | 应经过整理 |
| 以日期命名 | 以主题命名 |

建议让 Agent 定期从 Daily Notes 中提取值得长期保存的知识，但不要自动将所有临时讨论升级为最终结论。

## 8. AGENTS.md Strategy

### 8.1 Why AGENTS.md

希望不同目录拥有不同的 Agent 工作规则。

例如：

- `tasks/`：强调任务状态一致性和去重。
- `daily/`：强调历史记录与每日规划。
- `meetings/`：强调决策、Action Items 和事实准确性。
- `knowledge/`：强调知识提炼与内容维护。

`AGENTS.md` 是一种面向 AI 编码 Agent 的指导文件约定。

使用前应确认当前 Kiro 版本对嵌套 `AGENTS.md` 的发现、加载及优先级行为，不能假设所有 Agent 工具的实现完全一致。

### 8.2 Root AGENTS.md

文件：`AGENTS.md`

```markdown
# Personal Work Notes Rules

## General Principles

1. Use Markdown for all notes.
2. Keep task state in tasks/active.md.
3. Do not duplicate active tasks across files.
4. Preserve historical daily and meeting notes.
5. Extract action items from meeting notes.
6. Avoid creating duplicate tasks.
7. Prefer minimal edits over rewriting entire files.
8. Read only task-relevant files.
9. Do not assume tentative discussions are final decisions.
10. Ask for confirmation before changing important decisions.
```

根目录规则应当简短。

避免将大量具体技术背景写在根规则中。

### 8.3 tasks/AGENTS.md

文件：`tasks/AGENTS.md`

```markdown
# Task Management Rules

1. tasks/active.md is the source of truth for active tasks.
2. Preserve task IDs when editing existing tasks.
3. Avoid duplicate tasks.
4. Keep descriptions actionable and concise.
5. Update status when progress changes.
6. Move completed tasks to completed.md.
7. Preserve useful completion history.
8. Do not automatically delete unfinished tasks.
9. Do not mark a task complete without evidence or confirmation.
10. Reference related meetings or design documents when useful.
```

### 8.4 daily/AGENTS.md

文件：`daily/AGENTS.md`

```markdown
# Daily Notes Rules

1. Use YYYY-MM-DD.md for daily notes.
2. Follow the standard daily note structure.
3. Reference tasks from tasks/active.md.
4. Do not duplicate full task definitions.
5. Record progress, blockers, decisions and learnings.
6. Add new actionable tasks to tasks/active.md.
7. Preserve historical notes.
8. Do not overwrite previous decisions silently.
9. Keep daily notes concise.
10. Prefer editing today's note rather than unrelated history.
```

### 8.5 meetings/AGENTS.md

文件：`meetings/AGENTS.md`

```markdown
# Meeting Notes Rules

1. Preserve meeting facts and decisions accurately.
2. Separate Decisions, Action Items and Open Questions.
3. Identify owners for action items when known.
4. Extract personal action items into tasks/active.md.
5. Check for duplicate tasks before creating new ones.
6. Preserve unresolved questions.
7. Do not invent missing decisions or owners.
8. Reference related task IDs when available.
9. Avoid rewriting historical meeting conclusions.
10. Ask for confirmation when an action item is ambiguous.
```

### 8.6 knowledge/AGENTS.md

文件：`knowledge/AGENTS.md`

```markdown
# Knowledge Management Rules

1. Organize knowledge by topic, not date.
2. Prefer concise, reusable explanations.
3. Separate confirmed facts from hypotheses.
4. Reference source notes when relevant.
5. Avoid duplicating existing knowledge notes.
6. Preserve important technical details.
7. Update existing notes instead of creating duplicates.
8. Do not automatically promote tentative ideas to facts.
9. Use clear headings and searchable keywords.
10. Prefer minimal edits.
```

## 9. Kiro Steering vs AGENTS.md

Kiro 提供 Steering，可通过不同 Inclusion Modes 控制规则加载。

| Mechanism | Main Use |
|---|---|
| Root `AGENTS.md` | 仓库全局通用规则 |
| Nested `AGENTS.md` | 目录相关的工作规则 |
| Kiro `always` Steering | 每次交互都需要的简短规则 |
| Kiro `fileMatch` Steering | 特定文件匹配规则 |
| Kiro `manual` Steering | 按需调用的指导 |
| Kiro Skills | 可复用的多步骤工作流 |

推荐：

- 通用规则优先使用 `AGENTS.md`。
- 需要 Kiro 特殊加载机制时使用 Steering。
- 不要在两套配置中重复大量相同内容。
- 对于 Kiro 不能自动发现的目录规则，通过 Steering 或 Skill 显式引用。
- 通过实际测试确认目录规则是否生效。

## 10. Kiro Skills

推荐建立三个 Skill。

### 10.1 Daily Planning

用户输入：

> Plan my day.

Agent 工作流程：

1. 读取 `tasks/active.md`。
2. 读取最近一到两天的 Daily Notes（按需）。
3. 识别未完成任务、截止日期和阻塞项。
4. 根据优先级选择当天重点。
5. 创建当天 Daily Note。
6. 不复制完整任务数据库。

输出：

- Today's Focus
- Upcoming Deadlines
- Blocked Tasks
- Suggested Priorities

### 10.2 Meeting Processing

用户输入：

> Process today's meeting notes.

Agent 工作流程：

1. 读取指定会议记录。
2. 提取 Decisions。
3. 提取 Action Items。
4. 查找已有任务，避免重复。
5. 更新 `tasks/active.md`。
6. 补充关联会议链接。
7. 报告尚未确认的问题。

### 10.3 Daily Wrap-up

用户输入：

> Wrap up my day.

Agent 工作流程：

1. 读取当天 Daily Note。
2. 读取当前 Active Tasks。
3. 汇总任务进展。
4. 根据明确记录更新任务状态。
5. 将明确完成的任务归档。
6. 记录仍然存在的 Blockers。
7. 保留未完成任务在 `active.md` 中。
8. 不创建重复 Todo。

## 11. Token Optimization

### 11.1 Context Loading

推荐按需读取：

| Task | Required Context |
|---|---|
| Morning Planning | active.md + 最近 Daily Notes |
| Add New Todo | active.md |
| Update Task | 目标任务 + 必要历史 |
| Process Meeting | 会议记录 + active.md |
| Daily Wrap-up | 当天 Daily + active.md |
| Technical Research | 相关 knowledge 文件 |
| Weekly Review | 本周 Daily + Active/Completed Tasks |

原则：

- 不默认读取所有历史 Daily Notes。
- 不默认读取所有 Meeting Notes。
- 不把整个 Knowledge Base 加载到每次 Session。
- 优先读取文件索引、标题或相关段落。
- 长期结论写入 Markdown，而不是依赖 Chat History。

### 11.2 Minimal Edits

Agent 修改笔记时：

- 只更新相关任务或章节。
- 不重排不相关内容。
- 不修改无关日期的记录。
- 不重新生成整个文件。
- 避免不必要的格式变化。

### 11.3 Deterministic Automation

未来可以使用简单脚本完成：

- 创建 Daily Note。
- 生成日期和标题。
- 查询临近截止日期的任务。
- 统计完成任务。
- 根据 Task ID 搜索历史。
- 生成每周摘要的基础数据。

能用脚本完成的事情，不必每次调用 LLM。

## 12. Optional Task IDs & Metadata

初期不强制所有 Todo 都有 ID。

对于跨天、跨会议、长期跟踪的任务，推荐稳定 Task ID。

例如：

```markdown
- [ ] Update Temporal Auth Design
  <!--
  @taskid: task-a83f21
  @status: in-progress
  @related:
    - doc-91c4e8b37a2f60d5
  -->
```

规则：

1. Task ID 全局唯一。
2. 不随任务描述变化。
3. 不随日期变化。
4. 不重复生成已有任务。
5. 可以关联设计文档 ID、Section ID、会议记录。
6. 简单短期任务可以不添加 Metadata。

推荐使用与设计文档类似的随机 ID 机制。

但个人笔记不需要完整的章节依赖图。

### 12.1 Avoid Metadata Overengineering

不建议一开始实现：

- 所有 Todo 的复杂 Dependency Graph。
- 完整任务状态数据库。
- 自动任务调度器。
- 多 Agent 协作。
- 大量自定义 Metadata。
- 复杂的工作流引擎。

先保证日常使用方便。

## 13. Git Workflow

建议建立独立的 Private Repository。

### 13.1 Daily Workflow

早上：

1. Git Pull。
2. 让 Kiro 生成当天 Daily Note。
3. 查看 Today's Focus。

工作中：

1. 记录会议和想法。
2. 更新重要 Todo。
3. 让 Kiro 提取 Action Items。

下班前：

1. 执行 Daily Wrap-up。
2. 更新完成状态。
3. Git Commit / Push。

### 13.2 Example Commit Messages

```text
daily: update notes for 2026-11-12
tasks: update temporal auth progress
meeting: add auth design review
knowledge: summarize OIDC token validation
```

不需要为个人的每次 Markdown 修改创建 PR。

Git 主要负责历史追踪和多设备同步。

### 13.3 Privacy & Security

- 使用 Private Repository。
- 不保存密码、Token、私钥。
- 检查公司关于内部资料、会议记录和代码托管的规定。
- 不将不适合外部存储的工作信息推送到个人云端。
- 涉及敏感资料时使用公司批准的 Git 服务和 Agent 环境。

## 14. Suggested Rollout

### Phase 1: Minimal Setup

先实现：

- 一个私有 Git Repository。
- `tasks/active.md`。
- `daily/`。
- `meetings/`。
- 根目录 `AGENTS.md`。
- 各目录简短 `AGENTS.md`。

这一阶段不开发额外工具。

### Phase 2: Kiro Integration

增加：

- Daily Planning Skill。
- Meeting Processing Skill。
- Daily Wrap-up Skill。
- 自动检查任务重复。

### Phase 3: Optional Automation

如果实际有需求，再增加：

- Task ID 生成器。
- Task ID 全局索引。
- 自动生成 Daily Todo Snapshot。
- 每周工作总结。
- 任务与设计文档关联。
- 简单的 `workctl` CLI。

## 15. Final Recommendation

推荐组合：

**Private Git + Markdown + Active Tasks + Daily Notes + Meeting Notes + Directory AGENTS.md + Kiro Skills**

关键原则：

1. Todo 和 Daily Notes 分离。
2. Todo 当前状态统一维护。
3. 未完成 Todo 不需要每天手动复制。
4. Daily Notes 保留每天的历史。
5. Meeting Notes 提供决策和任务来源。
6. Knowledge Notes 保存长期有效的结论。
7. 使用目录级 `AGENTS.md` 表达不同内容的管理规则。
8. Kiro Skills 标准化日常规划、会议处理和下班总结。
9. 只读取相关内容，避免 Token 浪费。
10. 保持轻量，按实际需要逐步增加自动化。

最终希望实现：

**Write once, track continuously, retrieve context on demand.**

让个人工作记录既适合人类阅读，也适合 AI Agent 自动整理、追踪和利用。

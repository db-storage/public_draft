
<!--
@docid: doc-5b9f8d21e6a0473c
@type: engineering-practice
@status: proposed
@version: 1.1
@updated: 2026-11-12
@tags: [design-collaboration, markdown, kiro, agent, dependency-management]
@depends_on: []
-->

# AI-Assisted Software Design Collaboration Best Practices

## 1. Background & Goals

### 1.1 Background

团队处于软件设计阶段，主要特点：

- 存在总体设计、模块设计、业务流程设计、接口契约等多个 Markdown 文档。
- 总体设计尚未完全成熟，需要随着模块设计持续演进。
- 模块之间存在依赖，模块 A 的修改可能影响模块 B 或总体设计。
- 多人并行设计，每个人都有自己的 AI Agent，主要使用 Kiro。
- Agent Token 预算有限，希望避免反复读取大量设计文档。

### 1.2 Goals

1. 提高多人并行设计效率。
2. 保证跨模块设计的一致性。
3. 支持总体设计与模块设计双向演进。
4. 自动识别设计变更的潜在影响范围。
5. 降低 Agent 的 Token 消耗。
6. 保持方案轻量，避免过度工程化。

### 1.3 Core Principles

- **Docs-as-Code**：Git + Markdown 管理设计文档。
- **Single Source of Truth**：公共接口与核心架构决策有唯一权威来源。
- **Explicit Dependencies**：通过稳定 ID 声明重要的跨文档、跨章节依赖。
- **Incremental Impact Analysis**：只分析变更部分及潜在受影响部分。
- **Progressive Context Loading**：Agent 按需加载上下文。
- **Suspect Dependency**：上游变化触发下游重新确认，而不是自动认定下游错误。
- **Human Ownership**：关键设计决策和跨模块修改由 Owner 确认。
- **Deterministic First**：脚本能完成的操作不交给 LLM。

## 2. Recommended Architecture

推荐组合：

| Area | Solution |
|---|---|
| Document Storage | Git + Markdown |
| Document Structure | Architecture + Modules + Contracts + ADR |
| Stable Identity | Document ID + Section ID |
| Explicit Dependencies | HTML Comment Metadata |
| Index | Python-generated Dependency Index |
| Impact Analysis | Git Diff + Reverse Dependency Graph |
| Review State | Suspect Dependency |
| AI Agent | Kiro |
| Agent Rules | Kiro Steering |
| Agent Workflow | Kiro Skills |
| Automation | Python + Shell Hooks + CI |
| Human Collaboration | PR + CODEOWNERS + Impact Report |

### 2.1 MVP Scope

第一版只实现五项核心能力：

1. Stable Document / Section IDs。
2. Section-level `depends_on`。
3. Reverse Dependency Index。
4. Git Diff 到 Section 的映射。
5. Suspect Dependency Review。

暂不实现：

- 图数据库。
- 复杂依赖类型系统。
- 全量知识图谱。
- Multi-Agent 自动协商。
- 自动重写所有受影响文档。
- 全量自动语义分析。

## 3. Document Organization

推荐结构：

```text
project/
├── README.md
├── docs/
│   ├── index.md
│   ├── architecture.md
│   ├── contracts/
│   │   ├── identity-api.md
│   │   └── workflow-api.md
│   ├── modules/
│   │   ├── auth/
│   │   │   ├── README.md
│   │   │   └── design.md
│   │   └── workflow/
│   │       ├── README.md
│   │       └── design.md
│   ├── flows/
│   ├── adr/
│   └── changes/
├── .kiro/
│   ├── steering/
│   ├── skills/
│   └── specs/
└── scripts/
```

### 3.1 Document Responsibilities

| Type | Responsibility |
|---|---|
| Architecture | 总体架构、系统边界、核心约束 |
| Module Design | 模块内部设计与实现策略 |
| Contract | 跨模块接口、数据格式、错误语义 |
| Flow Design | 跨模块业务流程 |
| ADR | 重要架构决策及原因 |
| Module README | 模块摘要、依赖、Owner |
| Change Proposal | 跨模块变更与影响分析 |

### 3.2 Single Source of Truth

- 公共接口定义统一放在 Contract。
- 模块文档引用 Contract，不复制完整接口定义。
- 总体设计定义系统边界和关键约束。
- ADR 记录重要决策及其理由。
- 各模块 Owner 维护自己的详细设计。

### 3.3 Document Status

- `draft`：初步设计。
- `proposed`：等待评审。
- `accepted`：正式采纳。
- `deprecated`：已被取代。

Agent 不得将 Proposed 自动视为 Accepted。

## 4. ADR (Architecture Decision Record)

ADR 用于记录重要架构决策。

建议包含：

1. Background
2. Options
3. Decision
4. Rationale
5. Consequences
6. Status

示例：

`docs/adr/003-identity-model.md`

ADR 的价值不仅在于记录方案，还在于保留为什么作出该决策的上下文，减少重复讨论。

## 5. Markdown Metadata Specification

<!--
@secid: sec-9ab75d62e0c14f83
@depends_on: []
-->

### 5.1 Design Goals

通过隐藏在 Markdown 中的结构化 Metadata，实现：

- Stable Identity
- Cross-document References
- Section-level Dependencies
- Reverse Dependency Lookup
- Incremental Impact Analysis
- Automated Validation

推荐使用 HTML Comments 存储 Metadata。

这种格式不影响通常的 Markdown 可视化渲染，同时方便 Agent 和脚本解析。

注意：

- Metadata 是团队自定义约定，不是 Markdown 或 Kiro 内置能力。
- HTML 注释不会显示在正常渲染页面，但可能出现在 HTML 源码中。
- 不得在 Metadata 中保存凭据或其他敏感数据。

### 5.2 Stable IDs

使用两种 ID：

| ID | Purpose |
|---|---|
| `docid` | 唯一标识文档 |
| `secid` | 唯一标识章节 |

示例：

```text
doc-a83f1c725b9e4d02
sec-b32e8c91f4a67120
```

规则：

1. ID 全局唯一。
2. ID 不依赖文件名、路径或标题。
3. 重命名、移动、普通修改不改变 ID。
4. 已删除的 ID 不应重新用于其他内容。
5. 章节拆分或合并时，需要检查依赖并决定 ID 迁移。
6. CI 检查重复及无效引用。

推荐使用 UUID v4 或具有足够随机性的短 ID。

### 5.3 ID Generation

Python：

```python
import uuid

def new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:16]}"
```

职责划分：

| Task | Owner |
|---|---|
| 判断是否需要 ID | Agent |
| 生成 ID | 脚本，初期也可由 Agent |
| 定义依赖 | Agent + Owner |
| 校验 ID 唯一性 | CI |
| 保留已有 ID | Agent + CI |
| 拆分合并章节 | Agent + Owner |

### 5.4 Document-level Metadata

```markdown
<!--
@docid: doc-a83f1c725b9e4d02
@status: accepted
@owner: team-auth
-->

# Identity Contract
```

### 5.5 Section-level Metadata

文件：`docs/contracts/identity-api.md`

```markdown
<!--
@docid: doc-a83f1c725b9e4d02
-->

# Identity Contract

<!--
@secid: sec-b32e8c91f4a67120
@depends_on: []
-->
## Token Claims

定义 Token Claims...
```

文件：`docs/adr/003-identity-model.md`

```markdown
<!--
@docid: doc-91c4e8b37a2f60d5
-->

# ADR-003: Identity Model

<!--
@secid: sec-c39a25e71b84d602
@depends_on:
  - sec-b32e8c91f4a67120
-->
## Identity Mapping

依赖 Identity Contract 的 Token Claims。
```

### 5.6 Dependency Semantics

```text
A @depends_on B
```

表示：

- A 依赖 B。
- B 修改后，A 可能受到影响。
- A 不一定需要修改，但应重新评估。

推荐区分以下情况：

| Declaration | Meaning |
|---|---|
| `@depends_on: []` | 已检查，没有已知外部依赖 |
| 缺少 `@depends_on` | 尚未声明或维护 |
| `@depends_on: [sec-xxx]` | 依赖指定章节 |
| `@depends_on: [doc-xxx]` | 依赖整个文档 |

MVP 只支持普通 `depends_on`，不引入复杂的依赖类型。

未来可视需要区分：

- Contract Dependency
- Constraint Dependency
- Reference Dependency

### 5.7 Dependency Granularity

不要求所有章节都配置 Metadata。

优先标注：

1. 核心 Contract。
2. 跨模块设计章节。
3. 被其他文档引用的重要章节。
4. 关键架构决策。
5. 跨模块业务流程中的关键约束。

普通描述性章节可以不配置 Section ID。

避免 Metadata 维护成本超过收益。

### 5.8 Dependency Index

由脚本扫描 Markdown 自动生成：

```json
{
  "sec-b32e8c91f4a67120": {
    "doc_id": "doc-a83f1c725b9e4d02",
    "file": "docs/contracts/identity-api.md",
    "heading": "Token Claims",
    "line_start": 10,
    "line_end": 25
  }
}
```

建议保存为：

```text
.cache/design-index.json
```

Index 是派生数据，不需要人工维护。

文件名、路径、标题变化后重新生成即可。

### 5.9 Reverse Dependency Index

源文档只维护 `depends_on`。

脚本自动生成反向依赖：

```text
sec-b32e8c91f4a67120
  <- sec-c39a25e71b84d602
  <- sec-e728ab42d1f9056c
```

支持：

- Direct Dependents
- Transitive Dependents
- Potentially Impacted Sections

依赖查询由脚本完成，不需要 LLM。

## 6. Suspect Dependency Mechanism

<!--
@secid: sec-0c37a4e52d691f8b
@depends_on:
  - sec-9ab75d62e0c14f83
-->

### 6.1 Concept

借鉴需求工程中 Suspect Link / Traceability 的思想。

当一个被依赖的 Section 修改后，其下游依赖关系进入需要重新确认的状态。

原则：

**Upstream Changed ≠ Downstream Incorrect**

上游修改不代表下游必然错误，只代表需要判断是否受到影响。

### 6.2 Review States

建议 MVP 使用：

| State | Meaning |
|---|---|
| `suspect` | 上游发生修改，尚未确认影响 |
| `reviewed-no-change` | 已检查，下游无需调整 |
| `reviewed-updated` | 已检查，并完成下游调整 |

状态建议保存在 PR Impact Report 或 CI 结果中，不必写入源文档 Metadata。

如果需要持久追踪，可以后续引入独立 Review 记录。

### 6.3 Trigger

示例：

```text
Contract Section Changed
         |
         v
Git Diff identifies changed Section
         |
         v
Reverse Dependency Lookup
         |
         v
Mark Dependents as Suspect
         |
         v
Agent Semantic Review
         |
         v
Owner Confirmation
```

### 6.4 Example

变更：

```text
sec-identity-contract
```

依赖：

```text
sec-workflow-auth
sec-cli-login
```

自动生成：

```markdown
# Dependency Impact Report

## Changed Section

- sec-identity-contract

## Suspect Dependencies

- sec-workflow-auth
- sec-cli-login

## Required Review

- Workflow Owner
- CLI Owner

## Review Results

| Section | Status | Reason |
|---|---|---|
| sec-workflow-auth | suspect | Pending review |
| sec-cli-login | suspect | Pending review |
```

Agent 后续只阅读：

- 上游变更的 Git Diff。
- 下游受影响 Section。
- 必要的 Contract / ADR。

再判断实际影响。

### 6.5 Suspect Review Rules

1. 上游发生语义相关变更时，应重新检查下游依赖。
2. 脚本负责识别候选影响范围。
3. Agent 负责分析语义影响。
4. Owner 负责确认关键设计变化。
5. 不自动修改所有下游文档。
6. PR 合并前应处理关键 Contract 的未确认 Suspect。
7. 无需修改的依赖可以标记 `reviewed-no-change`。
8. 已修改的依赖可以标记 `reviewed-updated`。

### 6.6 Important Limitation

显式依赖图无法发现没有声明的关系。

因此：

- 依赖图可以帮助确定可能受影响的范围。
- 依赖图不能保证所有受影响的文档都已找到。
- 对关键 Contract，可以补充全文搜索或 Agent 语义检查。
- Agent 修改设计时，应评估是否需要新增或删除依赖声明。

## 7. Cross-module Change Workflow

### 7.1 Workflow

1. Module A 提出变更。
2. Git Diff 定位发生变化的 Section。
3. Dependency Index 找到直接及潜在间接依赖。
4. 自动生成 Suspect List。
5. Agent 执行语义影响分析。
6. 相关 Owner 确认 Contract / ADR。
7. 各 Module Owner 修改自己的设计。
8. PR Review + CI。
9. Merge 后生成新的 Index。

### 7.2 Impact Report

```markdown
# Design Change Impact Report

## Proposed Change
...

## Changed Sections
- sec-xxx

## Directly Impacted
- sec-yyy

## Transitively Impacted
- sec-zzz

## Suspect Dependencies
- sec-aaa
- sec-bbb

## Compatibility Risks
...

## Open Decisions
...

## Required Reviewers
...

## Review Results
...
```

### 7.3 Change Classification

| Change | Recommended Review |
|---|---|
| 模块内部修改 | Module Owner |
| 兼容性 Contract 变更 | Contract Owner + Consumer |
| 破坏性 Contract 变更 | 所有受影响 Owner |
| 架构级变更 | Architecture Review + ADR |
| 文档澄清 | 普通 PR |

## 8. Kiro Agent Practices

### 8.1 Recommended Collaboration Model

采用：

**One Kiro Agent per Developer + Shared Steering + Shared Skills**

不建议初期引入复杂的 Multi-Agent Framework。

### 8.2 Steering

`.kiro/steering/design-rules.md`

```markdown
---
inclusion: always
---

# Design Rules

1. Read docs/index.md as the entry point.
2. Load only task-relevant content.
3. Contracts are the source of truth for interfaces.
4. Respect Draft / Proposed / Accepted status.
5. Preserve existing Document and Section IDs.
6. Never invent referenced IDs.
7. Use the dependency index before cross-module changes.
8. Generate an Impact Report for cross-module changes.
9. Treat impacted dependencies as Suspect until reviewed.
10. Do not silently modify another module's design.
11. Prefer minimal diffs.
12. Run metadata validation after edits.
```

保持 Steering 简短，不把完整设计文档全部配置为 Always。

### 8.3 Shared Skills

推荐：

**design-change**

- 识别变更目标。
- 获取 Git Diff。
- 查询相关依赖。
- 输出 Suspect List。
- 加载相关 Section。
- 生成 Impact Report。
- 根据 Owner 确认更新设计。
- 运行校验。

**design-review**

- 检查 Contract 一致性。
- 检查 ADR 约束。
- 检查遗漏依赖。
- 审查 Suspect Dependency。
- 发现设计冲突和风险。
- 输出未解决问题。

### 8.4 Context Loading

采用四级上下文：

| Level | Content |
|---|---|
| L0 | 全局规则 |
| L1 | 项目索引、模块摘要 |
| L2 | 相关 Contract / ADR / Section |
| L3 | 完整设计文档和相邻模块 |

优先加载 L0–L2。

只有必要时加载 L3。

### 8.5 Git Diff First

```bash
git diff main...HEAD -- docs/
```

先定位变更，再读取依赖章节。

避免要求 Agent 比较全部设计文档。

### 8.6 Sessions

- 每个独立设计问题使用相对独立的 Session。
- 确认的决定写入 Git 文档。
- 不把 Agent Chat History 作为设计权威来源。
- 新 Session 从当前设计文档恢复上下文。

## 9. Automation & designctl

建议逐步实现：

```bash
# Generate IDs
designctl id new doc
designctl id new sec

# Build dependency index
designctl index

# Validate metadata
designctl check

# Query dependencies
designctl deps sec-xxx

# Reverse dependency impact
designctl impact sec-xxx

# Analyze changed sections
designctl impact --diff main...HEAD
```

职责：

| Operation | Implementation |
|---|---|
| ID generation | Python |
| Markdown parsing | Python |
| Dependency graph | Python |
| Git Diff | Git + Python |
| Suspect identification | Python |
| Semantic impact analysis | Agent |
| Design modifications | Agent + Owner |
| Final decisions | Owner |

CI 优先执行确定性检查。

只有必要时才调用 Agent。

## 10. Risks & Mitigations

### 10.1 Stale Dependencies

最大风险是依赖关系逐渐过时。

例如 A 新增对 C 的依赖，但没有更新 `depends_on`。

应对：

- Agent 修改设计时检查是否产生新的跨模块依赖。
- PR Review 检查依赖关系变化。
- 核心 Contract 要求较高的依赖覆盖率。
- 必要时增加全文搜索或语义检查。

### 10.2 Excessive Metadata

如果每个章节都要求 ID 和多个依赖，维护成本可能过高。

应对：

- 只标记关键依赖。
- 不强制所有章节都有 ID。
- 不强制所有章节声明 `depends_on: []`。
- 不引入过多依赖类型。

### 10.3 False Positives

上游设计变化不一定影响下游。

应对：

- 使用 Suspect 状态。
- Agent 做语义分析。
- Owner 确认。
- 不自动修改所有依赖者。

### 10.4 Incomplete Dependency Graph

没有显式声明的依赖无法自动识别。

应对：

- 使用依赖图作为主要候选来源。
- 用搜索和 Agent 发现潜在遗漏。
- 不将“无已知依赖”解释为“完全无影响”。

### 10.5 Section Split / Merge

章节拆分和合并可能引起依赖迁移。

应对：

- 不自动复用原 ID 指向不同语义对象。
- 对变化后的语义边界重新评估。
- 使用 Git 两个版本的 Index 进行比较。
- 必要时更新所有引用者。

## 11. Rollout Plan

### Phase 1: Basic Metadata

- 统一 Markdown 文档结构。
- 引入 Document ID 和 Section ID。
- 建立 Kiro Steering。
- 编写基础 ID 校验脚本。
- 优先标注关键 Contract。

### Phase 2: Dependency Tracking

- 引入 `depends_on`。
- 实现 Dependency Index。
- 实现 Reverse Dependency Lookup。
- 使用 Git Diff 定位变更 Section。
- 自动输出潜在受影响章节。

### Phase 3: Suspect Review

- 自动标记 Suspect。
- 生成 Impact Report。
- 共享 Kiro Design Review Skill。
- 在 PR 中记录 Review 结果。
- 针对关键 Contract 引入必要的评审要求。

### Phase 4: Optimization

根据实际数据决定是否继续：

- 自动发现遗漏依赖。
- 引入依赖类型。
- 增加 Architecture Reviewer Agent。
- 增强 IDE 集成。
- 优化 Token 消耗。

不提前引入复杂架构。

## 12. Effectiveness Validation

建议选择 3–5 个相互依赖的模块、约 20–50 个 Markdown 文档进行试验。

比较：

- A：普通 Markdown + Agent 搜索。
- B：Metadata + Dependency Index + Git Diff + Agent。

使用 10–20 次真实设计变更衡量。

| Metric | Expected Result |
|---|---|
| Token Consumption | 降低 |
| Missed Impacted Sections | 减少 |
| False Positive Suspects | 可接受 |
| Review Time | 缩短 |
| Metadata Maintenance Time | 保持较低 |
| Design Rework | 减少 |

成本评估不仅考虑 Token，还要考虑：

```text
Total Cost =
  Agent Token Cost
  + Human Maintenance Cost
  + Review Cost
  + Rework Cost
```

不能仅因为 Token 下降，就认定整体方案一定有效。

## 13. Related Industry Practices

可以参考：

### 13.1 IBM DOORS Next

借鉴：

- Stable requirement identity。
- Traceability。
- Suspect Links。
- Change Impact Analysis。

### 13.2 Jama Connect

借鉴：

- Requirement traceability。
- Upstream / Downstream relationships。
- Change review workflows。

### 13.3 Dendron

借鉴：

- Markdown Frontmatter。
- Stable Document IDs。
- Backlinks。

### 13.4 Backstage

借鉴：

- Stable entity references。
- `dependsOn` relationships。
- Reverse dependency queries。

这些系统的目标和实现各不相同，但相关思想可以用于轻量级 Markdown 设计管理。

## 14. Final Recommendation

推荐方案：

**Git + Markdown + Stable IDs + Explicit Dependencies + Reverse Index + Git Diff + Suspect Review + Kiro Skills**

核心理念：

1. 把 Markdown 变成可追踪的设计知识库。
2. 通过稳定 ID 消除文件路径、标题变化的影响。
3. 通过显式依赖实现确定性的影响范围查询。
4. 通过 Git Diff 实现增量分析。
5. 通过 Suspect Dependency 避免将潜在影响误判为确定错误。
6. 使用 Agent 完成语义分析，而非重复执行确定性工作。
7. 通过 Owner Review 保证跨模块设计决策的可靠性。
8. 保持 Metadata 和工具尽可能轻量。
9. 用真实实验衡量收益和维护成本。
10. 根据实际需要逐步演进，而非一次性建设完整平台。

最终目标：

**Make design documents incrementally analyzable and AI-friendly, while keeping human ownership and maintenance costs low.**

这是一种借鉴增量编译与需求追踪思想的轻量级设计文档管理方案。


<!--
@docid: doc-5b9f8d21e6a0473c
@type: engineering-practice
@status: proposed
@version: 1.0
@updated: 2026-11-12
@tags: [design-collaboration, markdown, kiro, agent, dependency-management]
@depends_on: []
-->

# AI-Assisted Software Design Collaboration Best Practices

## 1. 背景与目标

### 1.1 背景

团队处于软件设计阶段，主要特点：

- 存在总体设计、模块设计、业务流程设计、接口契约等多个 Markdown 文档。
- 总体设计尚未完全成熟，需要随着模块设计持续演进。
- 模块之间存在依赖，模块 A 的修改可能影响模块 B 或总体设计。
- 多人并行设计，每个人都有自己的 AI Agent，主要使用 Kiro。
- Agent Token 预算有限，希望避免反复读取大量设计文档。
- 希望充分利用 Agent，提高设计效率，同时保证设计一致性。

### 1.2 目标

1. 提高多人并行设计效率。
2. 保证跨模块设计的一致性。
3. 支持总体设计与模块设计双向演进。
4. 自动识别设计变更的影响范围。
5. 尽量降低 Agent 的 Token 消耗。
6. 避免引入复杂、维护成本高的工具和流程。

### 1.3 核心原则

- **Docs-as-Code**：使用 Git + Markdown 管理设计文档。
- **Single Source of Truth**：公共接口、契约和架构决策有唯一权威来源。
- **Explicit Dependencies**：使用稳定 ID 显式声明跨文档、跨章节依赖。
- **Incremental Analysis**：优先分析变更部分和受影响部分，而非全量重新分析。
- **Progressive Context Loading**：Agent 按需加载相关上下文。
- **Human Ownership**：设计决策及跨模块修改最终由相关 Owner 确认。
- **Deterministic First**：能由脚本完成的工作，不交给 LLM。

## 2. 整体技术方案

采用以下组合：

| 领域 | 方案 |
|---|---|
| 文档存储 | Git + Markdown |
| 文档结构 | Architecture + Modules + Contracts + ADR |
| 文档身份 | Stable Document ID |
| 章节身份 | Stable Section ID |
| 依赖关系 | HTML Comment Metadata |
| 依赖索引 | Python 脚本自动生成 |
| 影响分析 | Git Diff + Dependency Graph + Agent |
| Agent | 每人自己的 Kiro |
| Agent 规则 | Kiro Steering |
| Agent 工作流 | Kiro Skills |
| 功能设计 | Kiro Specs（按需） |
| 自动化 | Shell Hooks + CI |
| 设计评审 | PR + CODEOWNERS + Impact Report |

不建议初期引入完整的 Multi-Agent 框架或复杂的知识图谱系统。

## 3. Markdown 文档组织

### 3.1 推荐目录结构

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

### 3.2 各类文档职责

| 文档类型 | 主要职责 |
|---|---|
| Architecture | 总体架构、系统边界、核心约束 |
| Module Design | 模块内部设计、实现策略 |
| Contract | 跨模块接口、数据格式、错误语义 |
| Flow Design | 跨模块业务流程 |
| ADR | 重要架构决策及其理由 |
| Module README | 模块摘要、依赖、Owner、关键入口 |
| Change Proposal | 跨模块设计变更及影响分析 |

总体设计不应复制所有模块细节。

公共接口和协议应尽可能在 Contract 中定义，其他文档通过引用使用。

### 3.3 文档状态

建议使用：

- `draft`：初步设计。
- `proposed`：已形成方案，待确认。
- `accepted`：已正式采纳。
- `deprecated`：已废弃或被取代。

Agent 不能将 Proposed 方案自动视为 Accepted。

## 4. ADR：Architecture Decision Record

ADR 用于记录重要架构决策。

建议每项重要决策建立独立 Markdown 文件，例如：

`docs/adr/003-identity-model.md`

ADR 包含：

1. Background：决策背景。
2. Options：候选方案。
3. Decision：最终选择。
4. Rationale：选择原因。
5. Consequences：影响与取舍。
6. Status：决策状态。

ADR 不仅记录“怎么做”，还记录“为什么这样做”。

目的在于减少团队成员和 Agent 对既有决策的反复讨论。

## 5. Markdown Metadata 设计

<!--
@section_id: sec-9ab75d62e0c14f83
@depends_on: []
-->

### 5.1 设计目标

通过 Markdown 中不渲染的 Metadata，使设计文档具备类似源代码的以下能力：

- 稳定符号标识。
- 显式依赖声明。
- 跨文件引用。
- 依赖索引。
- 增量变更分析。
- 自动检查和诊断。

推荐使用 **HTML Comments + 自定义 YAML 风格 Metadata**。

HTML 注释通常不会显示在渲染结果中，但仍然存在于 Markdown 源文件中，Agent 和脚本可以读取。

注意：HTML 注释并非安全隔离机制，在部分 Markdown 渲染环境中，注释仍可能出现在生成的 HTML 源码中。

Metadata 语法和语义属于团队自定义规范，不是 Markdown 或 Kiro 内置标准。

### 5.2 稳定 ID 设计

使用两种 ID：

| ID 类型 | 用途 |
|---|---|
| `docid` | 唯一标识设计文档 |
| `secid` | 唯一标识设计章节 |

建议：

- ID 全局唯一。
- ID 与文件名、路径、标题、章节顺序无关。
- 文件重命名或移动时保留 ID。
- 标题修改或章节重排时保留 ID。
- 普通内容修改时保留 ID。
- 删除后的 ID 不用于其他对象。
- 章节拆分、合并时需要检查依赖并决定 ID 的保留或迁移。

ID 建议采用随机生成方式，例如 UUID v4。

示例：

```text
doc-a83f1c725b9e4d02
sec-b32e8c91f4a67120
```

16 个随机十六进制字符具有 64 位随机空间，适合小到中等规模的文档系统，但仍需要唯一性检查；若希望更强的唯一性保证，可使用完整 UUID。

### 5.3 文档级 Metadata

示例：

文件：`docs/contracts/identity-api.md`

```markdown
<!--
@docid: doc-a83f1c725b9e4d02
@status: accepted
@owner: team-auth
-->

# Identity Contract

...
```

其中：

- `docid` 是稳定身份。
- `status` 是设计状态。
- `owner` 是维护负责人。

文档路径只是存储位置，不是唯一身份。

### 5.4 Section 级 Metadata

示例：`docs/contracts/identity-api.md`

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

Token Claims 定义...

<!--
@secid: sec-d61e48c2a730b95f
@depends_on: []
-->
## Error Handling

错误处理定义...
```

另一个文档：`docs/adr/003-identity-model.md`

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

本章节依赖 Identity Contract
中的 Token Claims 定义。

<!--
@secid: sec-d75214a6f381e9b0
@depends_on: []
-->
## Token Validation

本章节没有声明的外部依赖。
```

这里采用全局唯一的 Section ID，因此引用时不需要写文件路径。

### 5.5 依赖声明规则

建议同时支持 Document 级和 Section 级依赖。

```yaml
@depends_on:
  - doc-a83f1c725b9e4d02
  - sec-b32e8c91f4a67120
```

含义：

- `doc-*`：依赖整个文档。
- `sec-*`：依赖指定章节。

依赖方向：

```text
A @depends_on B

表示：
A 依赖 B。
B 变更时，A 可能受到影响。
```

Metadata 约定：

| 情况 | 含义 |
|---|---|
| `@depends_on: []` | 显式声明没有已知外部依赖 |
| 缺少 `@depends_on` | 依赖尚未声明或未维护 |
| `@depends_on: [sec-xxx]` | 显式依赖指定章节 |
| `@depends_on: [doc-xxx]` | 显式依赖整个文档 |

不建议在每个章节中强制维护依赖关系。

建议优先为以下内容建立 Section ID：

- 被其他文档引用的章节。
- 存在跨模块依赖的章节。
- 核心 Contract。
- 重要架构决策。

依赖 Metadata 的位置建议固定在对应 Heading 之前。

脚本需要定义清楚：

- 注释与 Heading 的关联规则。
- Section 范围由 Heading 层级确定。
- 子章节的依赖是否影响父章节。
- 同一章节下多个 Metadata 块如何处理。
- 当章节被拆分、合并时的 ID 迁移规则。

### 5.6 ID 生成

推荐使用 Python：

```python
import uuid

def new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:16]}"

print(new_id("doc"))
print(new_id("sec"))
```

推荐职责划分：

| 工作 | 负责方 |
|---|---|
| 判断何时需要 ID | Agent |
| 生成新 ID | 脚本或 Agent |
| 定义依赖关系 | Agent + 人工 Review |
| 保持已有 ID 不变 | Agent 规则 |
| 校验唯一性与引用 | CI |
| 章节拆分、合并 | Agent 分析 + Owner 确认 |

初期可以允许 Agent 生成随机 ID，通过 CI 校验。

长期更推荐统一使用脚本生成，避免不同 Agent 产生不一致的格式。

### 5.7 自动生成 Document / Section Index

通过扫描 Markdown 自动生成索引：

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

Index 是脚本生成的派生数据，不需要人工维护。

可以保存到：

```text
.cache/design-index.json
```

如果文件移动或标题变化，只需要重新生成 Index。

### 5.8 反向依赖索引

文档中只维护 `depends_on`，不要求额外维护 `consumers`。

脚本自动构建反向依赖：

```text
sec-b32e8c91f4a67120
  <- sec-c39a25e71b84d602
  <- sec-e728ab42d1f9056c
```

用途：

当 `sec-b32e8c91f4a67120` 发生修改时，快速找到可能受到影响的章节。

依赖查询不需要 LLM。

## 6. 跨模块设计变更流程

<!--
@section_id: sec-0c37a4e52d691f8b
@depends_on:
  - sec-9ab75d62e0c14f83
-->

### 6.1 推荐流程

```text
1. Module A 提出设计变更
       |
2. Git Diff 确定变更内容
       |
3. Dependency Index 定位关联章节
       |
4. Agent 生成 Impact Report
       |
5. Owner 确认跨模块契约/架构决策
       |
6. 各 Module Owner 更新自己的设计
       |
7. PR Review + CI 检查
       |
8. Merge 后生成新的依赖索引
```

其中：

- 步骤 2、3、8 主要由脚本完成。
- 步骤 4、6 可使用 Agent。
- 步骤 5、7 保留人工决策。

### 6.2 变更分类

| 类型 | 示例 | 处理方式 |
|---|---|---|
| 局部修改 | 模块内部缓存方案调整 | Module Owner |
| 兼容接口变更 | 增加可选字段 | Contract Owner + 消费方 |
| 破坏性接口变更 | 删除已有字段 | 所有受影响 Owner |
| 架构级变更 | 修改认证架构 | Architecture Review + ADR |
| 文档澄清 | 修正描述错误 | 普通 PR |

跨模块设计修改原则上先分析影响，再执行修改。

### 6.3 Impact Report

推荐格式：

```markdown
# Design Change Impact Report

## Proposed Change

变更内容...

## Changed Sections

- sec-xxx

## Directly Impacted

- sec-yyy
- sec-zzz

## Potentially Impacted

- doc-aaa

## Compatibility Risks

风险...

## Required Decisions

待确认决策...

## Recommended Reviewers

- Auth Owner
- Workflow Owner

## Recommended Actions

建议的文档修改...
```

Impact Report 既供人工评审，也可供其他 Agent 使用。

### 6.4 增量影响分析

推荐采用：

1. `git diff` 获取变更范围。
2. 解析 Markdown Heading 和 Section ID。
3. 识别发生变化的 Section。
4. 查询反向依赖图。
5. 返回直接依赖及必要的传递依赖。
6. Agent 只阅读相关 Section。
7. Agent 判断实际语义影响。

注意：

- 依赖图识别的是可能受影响的范围，不代表所有依赖者都必须修改。
- 未显式声明的依赖无法通过依赖图可靠发现。
- 对关键 Contract 可以增加全文搜索或 Agent 语义检查。
- 删除、移动、拆分章节时应比较 Git 两个版本的索引，避免只靠变更后的 ID 信息。
- 同时修改章节内容及依赖声明时，应同时检查旧、新依赖关系。

## 7. Kiro Agent 使用实践

<!--
@section_id: sec-17bf83a6d42c905e
@depends_on: []
-->

### 7.1 不建议初期使用复杂 Multi-Agent

推荐模式：

**每人一个 Kiro Agent + 共享 Steering + 共享 Skills + Git PR。**

| 方案 | 建议 |
|---|---|
| 每人 Kiro + 共享规则 | 优先 |
| 专用 Architecture Reviewer Agent | 按需 |
| 每模块独立 Agent | 暂不需要 |
| 多 Agent 自动协商设计 | 暂不推荐 |

多个团队成员可以各自使用 Agent，但不必实现复杂的 Agent-to-Agent 自动通信。

### 7.2 Steering：公共规则

建议文件：

`.kiro/steering/design-rules.md`

```markdown
---
inclusion: always
---

# Design Rules

1. Read docs/index.md as the project entry point.
2. Load only task-relevant documents.
3. Contracts are the source of truth for interfaces.
4. Respect design status: Draft, Proposed, Accepted.
5. Identify dependencies before cross-module changes.
6. Never silently modify another module's design.
7. Preserve existing Document and Section IDs.
8. Generate new IDs only when required.
9. Never invent referenced IDs; resolve them from the index.
10. Prefer minimal diffs over full-document rewrites.
11. Report conflicts and unresolved questions explicitly.
12. Run metadata validation after design changes.
```

Steering 应保持简短。

不要把所有设计文档配置为 `always` 加载。

### 7.3 Steering 加载策略

| 类型 | 用途 |
|---|---|
| `always` | 少量全局规则 |
| `fileMatch` | 特定目录、模块规则 |
| `manual` | 大型架构评审指南 |
| `auto` | 可由 Kiro 按任务相关性判断的指导内容 |

具体支持方式和语法以当前 Kiro 官方文档为准。

### 7.4 Skills：共享标准工作流

建议优先创建两个 Skills。

**Skill A：design-change**

用于设计变更。

工作步骤：

1. 理解修改目标。
2. 读取项目 Index 和模块摘要。
3. 读取相关 Contract。
4. 使用脚本查询依赖关系。
5. 生成 Impact Report。
6. 等待必要的跨模块决策。
7. 修改批准范围内的文档。
8. 运行校验。
9. 输出最终变更摘要。

**Skill B：design-review**

用于设计审查。

重点检查：

- Contract 一致性。
- 已确认 ADR 的约束。
- 跨模块依赖是否遗漏。
- 设计冲突。
- 破坏性修改。
- 未解决的问题。
- 是否存在不必要的文档重写。

### 7.5 Specs 的使用原则

Kiro Specs 适用于明确功能的设计与实现。

建议：

- 复杂功能：使用 Requirements / Design / Tasks。
- 小型功能：使用简化 Spec。
- 架构探索：优先 Markdown + ADR。
- 公共接口：放到共享 Contract 中。

不要让不同 Feature Spec 各自维护公共接口的多个权威版本。

### 7.6 Hooks 与 CI

优先使用 Shell Hooks 和静态检查工具。

推荐检查：

- Document ID 唯一性。
- Section ID 唯一性。
- 引用目标是否存在。
- Markdown 链接是否有效。
- 依赖声明是否合法。
- 是否存在悬空引用。
- 关键 Contract 变更是否缺少 Impact Report。
- 是否修改了已有的稳定 ID。

只有需要语义理解时，才调用 Agent。

避免每次 Markdown 保存都触发全量 LLM Review。

## 8. Token 优化策略

### 8.1 Progressive Context Loading

采用四级上下文：

| 级别 | 内容 | 加载时机 |
|---|---|---|
| L0 | 全局协作规则 | Always |
| L1 | 项目索引、模块摘要 | 相关任务开始时 |
| L2 | Contract、ADR、具体 Section | 按依赖加载 |
| L3 | 完整设计文档及相邻模块 | 复杂分析时 |

理想情况下：

```text
User Request
    |
Project Index
    |
Relevant Module Summary
    |
Dependency Query
    |
Relevant Sections
    |
Agent Analysis
```

核心是避免 Agent 反复阅读整个项目。

### 8.2 Git Diff 优先

变更分析时使用：

```bash
git diff main...HEAD -- docs/
```

优先读取：

- 变更片段。
- 变更所在章节。
- 相关 Contract。
- 直接依赖章节。

只有在必要时扩大上下文。

### 8.3 每个模块提供简短 README

推荐包含：

- Responsibilities
- Inputs / Outputs
- Contracts
- Dependencies
- Consumers
- Owner
- Key Decisions
- Open Questions

Module README 是摘要，不应复制完整设计内容。

### 8.4 不把聊天历史当作设计状态

建议：

- 一个独立设计任务使用一个 Session。
- 重要决策及时写入 ADR、Contract 或模块设计。
- 新 Session 根据 Git 文档恢复当前状态。
- 保留简短 Open Questions，而不是依赖完整聊天记录。
- 对较长任务使用精简的任务状态摘要。

### 8.5 Agent 分析与脚本分析的边界

| 任务 | 优先实现 |
|---|---|
| ID 生成 | Python |
| ID 唯一性检查 | Python / CI |
| 文档解析 | Python |
| 依赖图构建 | Python |
| 反向依赖查询 | Python |
| Git Diff 解析 | Python / Git |
| 语义影响分析 | Agent |
| 架构取舍 | Agent 辅助 + 人工 |
| 设计文档修改 | Agent |
| 最终设计决策 | Owner |

**原则：确定性操作尽量不消耗 Token。**

## 9. 轻量级 designctl 工具

可以逐步实现一个简单的 CLI。

```bash
# 生成新的 Document ID
designctl id new doc

# 生成新的 Section ID
designctl id new sec

# 扫描 Markdown，生成索引
designctl index

# 检查 Metadata 和引用
designctl check

# 查看某章节的依赖
designctl deps sec-xxx

# 查看反向依赖
designctl impact sec-xxx

# 分析 Git 变更的影响
designctl impact --diff main...HEAD
```

建议将 Index 视为派生数据。

`designctl` 不负责最终的语义决策，而是向 Agent 提供精确、低成本的上下文定位能力。

初期不必一次性实现所有功能。

## 10. 分阶段落地

### Phase 1：基础规范

优先完成：

- Git + Markdown 统一管理。
- 文档目录和 Index。
- 模块 Owner。
- Document ID 和 Section ID 规范。
- Kiro Steering。
- 基础 ID 唯一性检查。

此阶段允许 Agent 自行生成随机 ID，由 CI 检查。

### Phase 2：依赖和变更治理

逐步增加：

- Section 级 `depends_on`。
- Contract 独立管理。
- ADR。
- Dependency Index。
- 反向依赖查询。
- Impact Report。
- PR Review 规则。

优先为核心 Contract 和跨模块依赖添加 Metadata，不强制一次性标注所有文档。

### Phase 3：Agent 工作流和增量分析

进一步实现：

- 共享 Kiro Skills。
- Git Diff 到 Section 的映射。
- 增量影响分析。
- 相关章节按需加载。
- 自动生成影响报告。
- 必要时增加 Architecture Reviewer Agent。

不建议在此阶段之前就建设完整的 Multi-Agent 协作系统。

## 11. 风险及注意事项

| 风险 | 应对措施 |
|---|---|
| Agent 修改已有 ID | Steering 规则 + CI |
| ID 重复 | 随机 ID + 全局唯一性校验 |
| 文件重命名导致引用失效 | 使用稳定 ID，不使用路径作为身份 |
| 章节拆分/合并 | 分析并迁移依赖关系 |
| 依赖声明不完整 | 核心契约强制标注 + PR Review |
| 依赖关系过度标注 | 先覆盖跨模块关键依赖 |
| Agent 大规模重写文档 | Minimal Diff 规则 |
| 同一接口多处定义 | Contract 作为权威来源 |
| LLM Review Token 过多 | 静态检查优先、按需触发 |
| 依赖图存在传递影响 | 支持直接和间接依赖查询 |
| Markdown Metadata 格式不统一 | 固定 Schema + Parser |
| Agent 自动判断错误 | Owner 审查关键设计 |

## 12. 衡量方案效果

建议关注：

| 指标 | 目标 |
|---|---|
| 每次设计变更的 Token 消耗 | 降低 |
| 跨模块影响识别遗漏率 | 降低 |
| Design PR 返工次数 | 降低 |
| 文档之间的契约冲突 | 减少 |
| Agent 每次读取的文档数量 | 减少 |
| 变更影响分析耗时 | 缩短 |
| Metadata 维护成本 | 保持较低 |

## 13. 最终建议

整体方案可以概括为：

**Git + Markdown + Stable IDs + Explicit Dependencies + Incremental Impact Analysis + Kiro Skills**

具体原则：

1. 不急于引入复杂 Multi-Agent。
2. 通过稳定 ID 建立跨文档、跨章节引用。
3. 通过 HTML Comment Metadata 声明依赖关系。
4. 通过脚本建立依赖索引和反向依赖图。
5. 使用 Git Diff 识别实际变化。
6. 使用脚本定位可能受影响的章节。
7. 由 Agent 判断语义影响并辅助修改。
8. 由相关 Owner 确认跨模块架构决策。
9. 将 Kiro Steering 保持精简，用 Skills 标准化工作流。
10. 逐步引入自动化，避免过度工程化。

这套方案的核心思路类似于 **Incremental Compiler（增量编译器）**：

| 编译器概念 | 设计文档系统 |
|---|---|
| Symbol | Document / Section ID |
| Import | `depends_on` |
| Symbol Table | Design Index |
| Dependency Graph | 文档依赖图 |
| Change Detection | Git Diff |
| Incremental Compilation | 增量影响分析 |
| Compiler Diagnostics | Metadata 校验 |
| IDE Assistance | Kiro Agent |

最终目标不是让 Agent 理解并记住整个项目，而是：

**让工具精确定位需要理解的内容，让 Agent 只对真正需要语义推理的部分进行分析。**

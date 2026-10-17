# 完整 schemas.sql 的生命周期同步

本工具处理一个 MySQL database 的**完整目标快照**。schemas.sql 只保存所有目标表最新的 CREATE TABLE，不包含 DROP/ALTER/RENAME 命令。删除是通过“OM 现有表减去目标表”得出，rename 通过显式 JSON 清单表达。

## 用法

先安装 requirements.txt，设置 OM_URL 和 OM_TOKEN（CI 使用 Secret/Context）。父级 OM DatabaseService、Database、DatabaseSchema 需要提前存在。

```bash
# 1. 完整快照转为 OM 请求模型；可在无网络环境执行
python mysql_ddl_to_om.py convert examples/schemas.sql \
  --service mysql_prod --database default --schema shop \
  --output models.json

# 2. 读取 OM 现状，生成差异计划；不会写入 OM
python snapshot_sync.py plan models.json \
  --exclusive-schema --output plan.json

# 有明确 rename 时，在 plan 命令上增加：
# --renames examples/renames.json

# 3. 执行计划，保存逐阶段执行记录
python snapshot_sync.py apply plan.json --journal apply-journal.json

# 计划有表 rename 时，需要明确接受“新 ID + 旧表软删除”的语义：
# python snapshot_sync.py apply plan.json --journal apply-journal.json \
#   --acknowledge-rename-replacement
```

`--exclusive-schema` 是明确的所有权声明：此工具独占管理指定 OM DatabaseSchema 内所有表；不在快照中的活动表将进入软删除计划。**不要用于混合来源共同维护的 Schema**。不同 DB 分别运行，使用不同 scope。delete 的对象只有 OM 元数据，工具不连接业务 MySQL，不执行任何业务 DDL。

## 支持的行为

| 场景 | 处理方式 |
|---|---|
| 一个文件多表 | 完整解析所有 CREATE TABLE；全部成功才写输出 |
| 新建表 | POST 创建，保留新 ID；不会盲目 upsert 覆盖并发创建 |
| 字段新增/类型修改/字段删除 | PATCH 完整 columns 与相应约束 |
| 普通字段更新 | 保留同名字段的 description/displayName/tags；DDL 注释存在时优先 |
| 删除表 | 最后执行 hardDelete=false 的软删除，绝不硬删除 |
| 同名软删除表重新出现 | restore 原 ID，再更新结构 |
| 表重命名 | 显式映射，创建/恢复新名字，迁移选定标注，验证后软删除旧名 |
| 列重命名 | 显式映射，迁移旧字段的 description/displayName/tags，表 ID 不变 |
| 外键 | 所有表和字段就绪后再建立最终外键，支持循环引用 |
| 空 DB | 必须显式允许空快照并调整删除阈值 |
| 重复同步 | 用最新状态重新 plan/apply；一致时不做写入 |
| 并发修改 | 全局基线检查，PATCH 中还包含 JSON Patch version/name test |
| 中途失败 | 立即停止，不继续删除；记录 journal，重新读取状态生成计划 |

### 重要：rename 的语义边界

核查 OM 1.12.0-release：TableRepository 没有启用 EntityRepository 的 renameAllowed，PATCH name 会被还原。不能声称通过 PATCH 实现了原实体表重命名。因此本工具明确使用**替换式 rename**，需要 `--acknowledge-rename-replacement`。

表 rename 会迁移：表 description/displayName/tags/owners/domains/extension，以及字段 description/displayName/tags。DDL 中已有注释覆盖迁移注释。

**不会迁移/保证连续性：**实体 ID、历史版本、血缘、测试用例、Profile、使用统计、列 extension 等。列 rename 对 OM 而言也可能是删旧加新，虽然本工具复制标注，不保证列血缘和测试引用连续。旧表保留为软删除实体，可供审计；目标名字以前已存在的软删除实体会被恢复，使用那个目标实体的 ID。

如果必须保留 ID 和全部关联对象，就需要你们部署的 OM 提供正式 rename 能力，并单独适配，不能通过客户端模拟出相同保证。

### rename 清单

```json
{
  "tableRenames": [{"from": "orders", "to": "customer_orders"}],
  "columnRenames": [
    {"table": "customer_orders", "from": "status", "to": "order_status"}
  ]
}
```

字段 rename 的 table 使用**最终表名**。普通列 rename 不需要同时填写 tableRenames。没有清单时，不猜测：旧表缺失按删除，新表出现按创建；字段也是删除/新增，不迁移原字段标注。

清单可以保留用于重复执行：旧名不再活动、新名已存在时会按当前结构更新。但清单不应跨越将来另一次重用旧名字的业务变更；每次清单应绑定当前 commit。拒绝链式 rename、交换名字、多对一、目标列冲突、源和目标都不存在等歧义场景。需要时拆为多个明确快照。

## 计划、阈值和空快照

plan.json 记录：scope、父级 ID、源文件哈希、bundle 哈希、当前实体基线、目标 payload、字段差异、软删除清单及已知限制。planHash 检查意外编辑，**不是签名或鉴权机制**；不要手改计划后执行。

- 默认普通表删除最多 10 张，且不超过原活动表数的 50%。明确 rename 的旧表不计入普通删除阈值，但仍需要 rename 语义确认参数。
- 想删除最后一张表时，schemas.sql 可以为空/仅注释，但必须显式配置：

```bash
python mysql_ddl_to_om.py convert schemas.sql \
  --service mysql_prod --database default --schema shop \
  --allow-empty --output models.json
python snapshot_sync.py plan models.json --exclusive-schema \
  --allow-empty --max-delete-ratio 1 --max-deletes 10 --output plan.json
```

这些是显式 CLI 参数，不需要交互式确认。可配置在 CI 中；阈值越大，允许的计划删除范围越大。解析失败绝不会转换为空快照。

## 外键和执行阶段

顺序是：
1. 创建或恢复所有目标名字，创建时暂不带 FOREIGN_KEY。
2. 更新所有本地字段、主键和唯一约束，必要时暂时移除旧外键。
3. 写入所有最终外键（包括循环引用）。
4. 重新 GET 验证目标结构。
5. 最后软删除旧表/旧名字。

同一 scope 的外键目标必须存在于最终快照，并包含对应字段，否则 plan 直接失败。跨 Schema 外键会在 apply 开始写入前检查目标活动表和列存在，但不管理外部 Schema。字段约束列顺序对比遵循 OM 的集合表达；不要用此目录模型代替 MySQL 执行语义校验。

## 失败、重跑与并发

这是多 API 流程，**不是跨表事务，也没有自动回滚**。创建/更新部分表后失败时，它们保留已经完成的状态；旧表只在验证阶段通过后才开始软删除。删除阶段自身也可能部分成功。

读请求可重试；POST/PATCH/DELETE/restore 不自动重发，避免超时后不知道请求是否已成功而重复修改。失败后：
1. 查看 apply-journal.json（会标记 failed_replan_required）。
2. 用相同目标快照重新运行 plan，读取真实 OM 状态。
3. 再执行新计划；不要继续执行旧计划。

表 rename 中途失败后，旧名和新名可能同时活动。默认计划拒绝这种冲突。确认是刚才部分执行留下的目标后，在 **plan** 上加 `--resume-renames`，用原清单重新规划；随后 apply 仍需 rename 语义确认参数。这个参数不能用来随意覆盖已有的另一个业务表。

同一个 DB 的任务必须在 CI 中串行化；外部 Connector 不应同时更新同一结构。执行前比较完整 baseline，PATCH 通过 version/name test 进一步检测冲突，但初始检查、POST 和软删除之间仍有竞态窗口（DELETE API 没有客户端原子版本条件），它不提供锁或完整 CAS 保证。旧 commit 不应在新 commit 发布后重新 plan 覆盖；CI 应验证发布的目标 revision。

父级查询、列表分页（include=all）、跨作用域检查、重复 cursor 检查均已实现。Bot 需要读取父级及表、创建、更新、恢复、软删除权限。

## 验证状态与限制

测试覆盖真实转换器 + 有状态 OM 测试替身 + HTTP 请求参数 mock；未运行真实 OM 服务。部署版本未提供，基于 OM 1.12 请求模型和服务端源码设计。上线前在测试 OM 验证：JSON Patch test、完整 columns 删除行为、restore、Bot 权限、实体 soft delete 和标注保留。服务端若忽略写入，目标回读校验会阻止随后的旧表删除。对比时已考虑服务端将 dataTypeDisplay 转成小写的行为；枚举原始大小写仍保留在 schemaDefinition。主键仅在 tableConstraints 中表达，不与字段 PRIMARY_KEY 重复。

MySQL 解析能力沿用 README.md 的范围；不是所有 MySQL 语法都支持，不进行 MySQL 服务端语义校验。新增生命周期功能不会消除这些解析边界。

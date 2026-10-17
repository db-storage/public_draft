# Git source of truth：PR 增量与全量初始化

这是最新推荐入口：`pr_diff_to_om.py`。它和 `mysql_ddl_to_om.py` 共用 DDL 转换代码，并共用 `comment_annotations.py` 的安全标签解析。**生成时不连接 MySQL，不读取、不写入 OM，不需要 OM_URL/OM_TOKEN。**

## 两个模式

| 模式 | 输入 | 输出 |
|---|---|---|
| diff | PR base/head commit | 只生成新增、变更、移除的表对应请求 |
| full | 一个 head commit | 强制为配置内所有现存表生成 upsert 请求；不产生 DELETE |

实现不是把 patch 的新增 SQL 行送进 parser，而是用 Git diff 找出受影响的 schemas.sql，再从两个 commit 读取完整文件，分别解析、按表名比较。Git 的历史是唯一比较依据，不与 OM 现状比较。

## 配置

建立 `om-mapping.json`，参考 examples/git-sync/om-mapping.json：

```json
{
  "databases": [
    {"path":"mysql/shop/schemas.sql","service":"mysql_prod","database":"default","schema":"shop"},
    {"path":"mysql/payment/schemas.sql","service":"mysql_prod","database":"default","schema":"payment"}
  ]
}
```

路径相对 Git 仓库根目录；database 是 OM 的 Database 容器名，schema 是 MySQL 数据库名。父级 OM Service/Database/Schema 必须提前存在。本工具不生成父级连接配置。

配置必须覆盖相关 schemas.sql：diff 模式发现变更的未配置 schemas.sql 会失败；full 模式发现仓库中的未配置 schemas.sql 也会失败，避免遗漏数据库。full 模式要求每个配置 scope 至少有一个真实存在的文件；空 DB 可以保留空文件或注释文件。历史路径不再存在时应维护配置，而不是误以为文件被读取成功。

配置作为本次运行的可信映射传入，工具记录其哈希，不自动比较映射配置的历史版本。Service/Database/Schema 映射变更属于目录迁移，不能当普通表结构变更处理，应单独制定方案。

## PR 增量

```bash
pip install -r requirements.txt
python pr_diff_to_om.py --mode diff \
  --repo /path/to/ddl-repo \
  --base "$PR_BASE_SHA" --head "$PR_HEAD_SHA" \
  --config om-mapping.json --output om-artifact
```

默认比较 `merge-base(base, head) → head`，等同于 PR 的三点 diff 语义，不会把目标分支独有的新表误判成 PR 删除。

合并后发布时，如果已知实际发布前后两个 commit，应使用：

```bash
python pr_diff_to_om.py --mode diff \
  --repo /path/to/ddl-repo \
  --base "$BEFORE_SHA" --head "$AFTER_SHA" --comparison direct \
  --config om-mapping.json --output om-artifact
```

需要本地 Git 中存在两个 commit 和共同祖先；CI checkout 请获取足够历史。工具不自行 fetch，不调用 GitHub API，因此适合 GitHub Enterprise 和 CircleCI。读取 commit 中的 blob，忽略工作区未提交修改；拒绝 SQL 文件为软链接、目录或 submodule。output 必须是新目录，避免旧制品残留。

## 全量初始化

```bash
python pr_diff_to_om.py --mode full \
  --repo /path/to/ddl-repo --head "$COMMIT_SHA" \
  --config om-mapping.json --output om-init-artifact
```

无需 base。即使仓库没有任何变化，也会输出全部已配置 DB 的所有 CREATE TABLE。这里的“全部存量”指 **Git 中的全部配置表**，不是 OM 或生产数据库扫描结果。它不删除 OM 中额外存在的表。已有同名表由 PUT 更新，不同名的 OM 资产不会被处理。

## 输出与 OM API

| 文件 | 内容 | 能否直接作为 OM 请求体 |
|---|---|---|
| om-requests.json | commit、变更摘要、warnings 和有序 requests 清单 | 整个外层对象不能直接上传，需要 CI 消费 requests |
| upserts.json | 所有新增/修改/全量表的最终 CreateTableRequest 数组 | 是标准表请求数组，可用于 OM bulk 接口；不包含删除，且不能替代完整执行顺序 |
| 000-put.json 等 | 每一步的标准 JSON 请求体 | 可结合清单中的 method/path/query 直接提交 |
| summary.md | 新建、更新、删除、rename 报告 | 否，用于 PR/制品审查 |

request 示例：

```json
{
  "method":"DELETE",
  "path":"/api/v1/tables/name/mysql_prod.default.shop.old_table",
  "query":{"hardDelete":"false","recursive":"true"},
  "contentType":"application/json",
  "tableFqn":"mysql_prod.default.shop.old_table"
}
```

生成顺序：
1. PUT /api/v1/tables，为所有变化表/全量表提交完整字段，但先不附 FOREIGN_KEY。
2. PATCH /api/v1/tables/name/{fqn}，按 Git 完整快照设置字段、最终约束、DDL、描述和标签。此时所有新表都已存在，可处理循环外键。
3. DELETE /api/v1/tables/name/{fqn}，按名称软删除 Git 中消失的表。

PATCH 的 body 是标准 JSON Patch 数组，Content-Type 是 application/json-patch+json。它也绕过 Bot PUT 对旧描述的保留策略，使 Git 中注释更新/删除能明确表达。此新版以 Git 为权威，**最终表描述、表标签及字段描述/标签也按 Git 替换；不会保留未写入 Git 的人工标注。** 如果需要保留这类 OM 信息，应另行划定字段归属，不能在不读取 OM 时声称完整保留未知标注。

清单不含 GET，也没有根据 OM 状态计算出的 UUID、version 或补丁索引。API 执行是后续 CI job 的职责。例如在受信任的发布 job 中顺序消费：

```python
# 以下只示范消费标准请求格式；本包生成器不会自动运行它。
import json, os, requests
manifest = json.load(open("om-artifact/om-requests.json"))
for op in manifest["requests"]:
    response = requests.request(
        op["method"], os.environ["OM_ORIGIN"].rstrip("/") + op["path"],
        params=op.get("query"), json=op.get("body"),
        headers={"Authorization": "Bearer " + os.environ["OM_TOKEN"],
                 "Content-Type": op["contentType"]},
        timeout=(10, 60), allow_redirects=False,
    )
    response.raise_for_status()  # 失败即停止，不继续执行删除
```

OM_ORIGIN 指源站，如 https://om.example.com（不带 /api）。该示例不是事务、锁、自动恢复或完整发布器；认证、版本、权限、软删除重放、已有同名软删除表重建行为须在部署的 OM 上测试。上一步成功后下一步仍可能失败，不能自动回滚。重跑旧删除清单可能影响后来重建的同名表，因此必须由 CI 保证目标版本和严格发布顺序。

## drop 和 rename

- 新 Git 版本缺少旧表：产生针对旧 FQN 的 DELETE；不扫描 OM、不删除 Git 历史之外的表。
- 文件删除：从旧 commit 读出该文件全部表，生成删除操作。
- 文件路径搬迁：若旧/新路径配置到相同 scope，会按整体前后快照比较，不当作表 rename。迁移 PR 中配置需要同时包含旧路径和新路径别名；同一时刻不能重复定义同一张表。
- 表名变化：默认是 create + drop。工具不通过“结构相似”猜测 rename。
- 可以给 `--renames examples/git-sync/pr-renames.json` 明确把一对 create/drop 标注成 rename。请求仍是 upsert 新名 + 删除旧名，**不保留 OM 原实体 ID，也不迁移 OM 的历史、血缘、测试或人工标注**。与旧 snapshot_sync.py 的标注迁移模式不同。
- 列改名按完整 columns 表达删除/新增，不猜测，也不迁移 OM 列标注。

## COMMENT / 信息安全等级

表 COMMENT 和列 COMMENT 都支持。每条机器标记独占一行，普通文字成为 description：

```sql
email VARCHAR(128) COMMENT '用户邮箱
@om.security=L3
@om.tag=PII.Email'
```

映射为：

```json
{
  "description":"用户邮箱",
  "tags":[
    {"tagFQN":"PII.Email","source":"Classification","labelType":"Manual","state":"Confirmed"},
    {"tagFQN":"Security.L3","source":"Classification","labelType":"Manual","state":"Confirmed"}
  ]
}
```

- `@om.security=L3` 使用默认 Classification `Security`；可用 `--security-classification DataSecurity` 改为 DataSecurity.L3。
- `@om.tag=PII.Email` 指定精确 Tag FQN；多个标签重复写多行，重复值会去重。
- OM 中这些 Classification/Tag 必须预先创建。生成器不查询/创建安全分级体系，也不会推断 L3 代表什么；这由公司治理规范决定。
- 原始 COMMENT 保留在 schemaDefinition；description 去掉机器标记行。
- 同列冲突安全等级、未知/格式错误的 @om 指令直接失败。
- 仅修改等级/标签也能在 diff 中识别；删除标记会输出空 tags，以 Git 为权威清除标注。
- `-- @om.security=L3` 这类普通 SQL 行注释不作为列标记解析；本版只解析明确绑定表/列的 COMMENT 字面量。任意 JSON 注释或公司自定义 annotation 格式不自动猜测。

## CI 入口

附带 `schema-ci.sh`，可由 GitHub Actions/CircleCI 调用：

```bash
# PR job
export SCHEMA_MODE=diff
export SCHEMA_REPO=/path/to/ddl-repo
export SCHEMA_BASE_SHA=...
export SCHEMA_HEAD_SHA=...
export SCHEMA_MAPPING=/path/to/om-mapping.json
export SCHEMA_OUTPUT_DIR=om-artifact
bash schema-ci.sh

# 初始化 job
export SCHEMA_MODE=full
export SCHEMA_HEAD_SHA=...
export SCHEMA_OUTPUT_DIR=om-init-artifact
bash schema-ci.sh
```

GitHub pull_request 事件使用 event.pull_request.base.sha / head.sha；push 发布使用 event.before / event.after 并设置 SCHEMA_COMPARISON=direct。不要把一次多 commit push 的 HEAD^ 误当发布前版本。全零 before（首次创建分支）不支持 diff，应选 full 或指定已同步的真实基线。CircleCI 需由调用者提供相应 base/head，不能仅凭 CIRCLE_SHA1 推断发布前状态。

PR job 只生成和上传制品，无需 OM Secret。merge 后在可信发布 job 上使用实际合并结果生成请求。同一 DB 串行发布，检查目标 commit；不读取 OM 意味着无法发现漂移、缺失的历史变更或并发修改。这是 Git diff 模式的明确取舍。首次接入先 full 初始化，之后按顺序执行 diff；漏发后应补齐变更或重新 full（它仍不会清理 OM 额外资产）。

## 示例与验证

examples/git-sync/before.sql / after.sql 展示一张表新增、一张修改、一张删除，以及安全等级 L2→L3。diff-output / full-output 包含实际工具生成的标准请求体和清单。

测试使用本地临时 Git 仓库创建真实 commit，覆盖 merge-base/direct、路径迁移、文件增删、空文件、全量初始化、多 DB、未配置路径、脏工作区、软链接、注释、安全标签、外键循环和请求顺序；不访问真实 OM。SQL 方言支持范围沿用原转换器说明。

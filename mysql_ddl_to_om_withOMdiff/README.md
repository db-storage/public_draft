# MySQL DDL → OpenMetadata

**新版：完整多表快照、删除、恢复、表/列重命名请使用 `snapshot_sync.py`，见 [SNAPSHOT_SYNC.md](SNAPSHOT_SYNC.md)。本页的 `submit` 是旧版只创建/更新的接口。**

读取 Git checkout 后的完整 MySQL `CREATE TABLE` 文件，用 SQLGlot 解析，生成 OpenMetadata `CreateTableRequest` JSON。无须连接或启动 MySQL，无须自己实现 SQL 词法/语法分析器。转换与提交分开，适合 CI 先审查输出，再在 merge 后提交。

## 1. 快速运行

Python 3.10+（本次使用 Python 3.12）。解压后进入本目录：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python mysql_ddl_to_om.py convert examples/orders.sql \
  --service mysql_prod --database default --schema shop \
  --output models.json
```

多个文件可以作为位置参数传入，例如 `schema/*.sql`。每个文件可以有多条完整 CREATE TABLE，所有输入必须属于同一目标 MySQL database。不同 database 分别调用。

- `--service`：OM 中的 DatabaseService 名称，例如 `mysql_prod`。
- `--database`：OM 中的 Database 容器名称，例如 `default`。它与 MySQL 数据库名不是一回事；请与公司现有 OM 目录/Connector 命名一致，不要直接假设一定叫 default。
- `--schema`：目标 MySQL 数据库名，同时作为本工具使用的 OM DatabaseSchema 名称，例如 `shop`。
- 本例父级 FQN 是 `mysql_prod.default.shop`，表 FQN 是 `mysql_prod.default.shop.orders`。
- SQL 中有 `shop.orders` 时会检查 shop 与 `--schema` 完全一致；未限定数据库的 orders 使用传入的 schema。
- 输出为 bundle，`tables` 数组中的每个对象才是一个 API 请求体；不要把整个 bundle 直接 PUT 给 OM。
- 同一表不能在一批文件中重复出现。转换失败返回非零退出码，不写入部分结果。旧输出文件可能仍存在，CI 必须检查退出码，不要在失败后继续发布旧文件。

## 2. 提交到 OM

先在 OM 中创建对应 Service、Database、DatabaseSchema。Bot 需要读取父级、创建和更新目标表的权限。工具只更新表，不创建父级，也不会连接源数据库。

```bash
export OM_URL='https://om.example.com'  # 也接受 https://om.example.com/api
# 由 CI 的 secret/context 注入 OM_TOKEN，避免写进源码和命令行
python mysql_ddl_to_om.py submit models.json
```

提交使用 `PUT /api/v1/tables`。提交前 GET 检查所有父级 Schema 存在；提交失败返回非零状态。429/500/502/503/504 和部分网络故障最多重试 3 次。写入是逐表执行，不是跨表事务；中途失败可能已经成功写入前面的表，修复后可以重跑相同 bundle。服务器的表版本和事件行为以你们部署版本为准。

仅本地调试 HTTP 时显式加 `--allow-http`。默认验证 TLS，不跟随重定向，不打印 Bot Token。

正式接入前应先在测试 OM 上检查新增、字段修改、字段删除时的行为。完整 `columns` 列表具有替换/删除语义，不能传仅新增字段的列表；并且需要验证当前版本对人工注释、标签、Owner 的保留行为。本工具不额外做 GET 合并或保护人工编辑，避免多个同步源同时写同一表结构。

## 3. 转换范围

| 信息 | 输出 |
|---|---|
| 表名、字段名、顺序 | `name`、`ordinalPosition` |
| 整数、浮点、DECIMAL、CHAR/VARCHAR、二进制、文本、BLOB、时间、JSON、YEAR、BIT、ENUM/SET | `dataType` + `dataTypeDisplay` |
| VARCHAR/CHAR/BINARY/VARBINARY 长度 | `dataLength` |
| DECIMAL/FLOAT/DOUBLE 显式精度和小数位 | `precision`、`scale` |
| 表和字段注释 | `description` |
| NULL / NOT NULL | `constraint` |
| 单列、联合主键和唯一约束 | `tableConstraints`；主键字段使用 NOT_NULL，不重复写 PRIMARY_KEY |
| 外键 | 本地 columns + 目标 referredColumns FQN |
| 原始建表定义 | `schemaDefinition` |

细节：
- UNSIGNED 映射到相同宽度的 OM 整数枚举，在 `dataTypeDisplay` 中保留 UNSIGNED。MEDIUMINT 映射 INT；LONGTEXT/TINYTEXT 映射 TEXT。OM 类型是目录分类，不是无损 MySQL 执行类型。
- CHAR/BINARY 省略长度时按 MySQL 默认值 1 输出；VARCHAR/VARBINARY 缺少长度时报错。
- TINYINT(1) 仍为 TINYINT，不擅自当成 BOOLEAN；BOOL 按解析器归一化为 BOOLEAN。
- TIMESTAMP 映射 TIMESTAMP，DATETIME 映射 DATETIME。时间小数精度、BIT 位数、整数显示宽度、ENUM/SET 值列表保留在 `dataTypeDisplay`，不塞入含义不符的 dataLength/precision。
- 所有主键统一写表级 PRIMARY_KEY，相关字段标记 NOT_NULL；OM 拒绝同时在字段和表级重复表达 PRIMARY_KEY。
- 一个文件仅一张表时 `schemaDefinition` 保存原文；多表文件为每张表保存 SQLGlot 规范化后的对应建表语句。源文件 SHA-256 保存在 bundle 的 sources 中。
- 默认值、自增、ON UPDATE、生成列公式、CHECK、普通索引、引擎、字符集等保存在 `schemaDefinition`，并在 warnings 中明确列出，未成为独立结构化属性。
- `--strict` 会在存在上述任何 warning 时失败，也包括 ENGINE/CHARSET。适用于要求全部元数据都结构化表达的检查；普通采集可不加，审查 warnings 即可。
- 外键默认指向同一 service/database 容器，支持其他 MySQL database（Schema）的引用；不自动创建目标表、不排序外键依赖、不推导 relationshipType，相关目标需要提前存在或按依赖顺序上传。

不支持的类型、表达式/前缀唯一索引、未知约束/表选项直接报错，不降级为 UNKNOWN。
当前明确拒绝 ALTER、DROP、CTAS、CREATE LIKE、临时表、MySQL 可执行注释 `/*! ... */`、POINT 等未覆盖空间类型及该解析器不能可靠读取的语法（如测试中的 ZEROFILL）。这是一版明确语法边界的工具，不声称覆盖所有 MySQL DDL。

**SQLGlot 是解析器，不是 MySQL 验证器。** 能生成 AST 不意味着 MySQL 一定接受该 DDL；没有临时数据库就不能获得与服务端完全一致的语法/语义验证。SQL_MODE、版本相关行为不在本工具中模拟。实际仓库的 DDL 样本需要加入回归测试。

## 4. 可选：使用部署版本 SDK 校验请求

JSON 输出按 OM 1.12 的官方表模型编写。你们未提供 OM 版本，所以必须按实际部署版本验证。`--validate-sdk` 可在转换或提交前用已安装 SDK 的 `CreateTableRequest` 校验全部请求。

在单独环境安装与服务端兼容的 `openmetadata-ingestion` 完整依赖，然后执行：

```bash
python mysql_ddl_to_om.py convert examples/orders.sql \
  --service mysql_prod --database default --schema shop \
  --output models.json --validate-sdk
```

SDK 环境依赖较多；请检查与固定 SQLGlot 版本的依赖兼容性。默认离线转换只需 requirements.txt 中两个包，REST 提交无需安装 ingestion。

如果已有 SDK client，可直接复用转换函数：

```python
from pathlib import Path
from mysql_ddl_to_om import convert_files
from metadata.generated.schema.api.data.createTable import CreateTableRequest

bundle = convert_files(
    [Path('schema/orders.sql')],
    service='mysql_prod', database='default', schema='shop',
)
for payload in bundle['tables']:
    # client 是你们已配置好 Bot Token 的 OpenMetadata SDK client
    client.create_or_update(CreateTableRequest(**payload))
```

以后包成自定义 Connector 时，可以在 Source._iter 中生成 `Either(right=CreateTableRequest(**payload))`，交给标准 metadata-rest Sink 写入，解析和映射函数不变。

## 5. 测试

新增生命周期同步测试包含快照对比、标注迁移、rename 中途失败恢复、软删除、外键循环、分页、并发变化和请求参数检查。全套结果见 VALIDATION.md。

```bash
pip install -r requirements-dev.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

禁用第三方 pytest 自动插件可避免 ingestion 安装包自带插件影响本项目测试。没有安装 SDK 时，官方模型校验测试自动跳过。已完成 54 项转换/HTTP mock 测试；另用安装的 OM 1.12.0.0 生成模型验证示例及外键请求，合计 55 项通过。模型校验只加载 generated schema，没有启动整个 ingestion runtime。

没有连接真实 OM 服务；API 的权限、版本行为、外键目标校验需要接入你们环境后验证。

## 6. CI 接入建议

1. Checkout 精确 commit，转换完整 CREATE TABLE 文件，检查非零退出码和 warnings。
2. 将 models.json 与源 commit SHA 一起作为制品保存；SHA-256 用于核对来源，不证明 DDL 已执行。
3. 合并后发布与目标 commit 一致的制品。同一目标串行执行，避免旧版本晚完成覆盖新版本。
4. 文件删除/表重命名需要单独设计显式操作。本工具不会根据缺失文件自动删表。
5. merge 同步表示仓库中的预期结构；若目录必须代表生产已执行状态，应在 Ticket 成功后发布相应 commit 的制品。

## 参考

- SQLGlot：https://github.com/tobymao/sqlglot
- OM 表模型：https://github.com/open-metadata/OpenMetadata/blob/1.12.0-release/openmetadata-spec/src/main/resources/json/schema/entity/data/table.json
- OM CreateTableRequest：https://github.com/open-metadata/OpenMetadata/blob/1.12.0-release/openmetadata-spec/src/main/resources/json/schema/api/data/createTable.json
- OM 自定义 Connector：https://docs.open-metadata.org/latest/connectors/custom-connectors

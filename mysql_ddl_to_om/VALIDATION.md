# 当前版本验证：Git PR diff / full / 安全标签

2026-10-17 最新运行结果：**116 passed, 1 skipped**，共收集 117 项测试。

- Git 模式使用真实本地临时 Git 仓库和 commit，覆盖 PR merge-base、直接 base/head 对比、全量强制生成、多 DB、文件增删/移动、表字段变化、rename 清单、格式变化忽略、带点/空格/中文标识符、外键循环、COMMENT 分级和标签，以及 CI shell 入口。
- 生成器无 OM GET/写入；没有连接真实 MySQL/OM。完整 SDK 当前环境未安装，因此官方生成模型校验测试自动跳过。此前版本的模型验证记录保留在下方，不能视为本次新版端到端服务验证。
- CLI 的 diff/full 共用 Git 快照读取、原 DDL 转换器和 comment_annotations 模块。输出包括标准 API 请求体与有序 CI 请求清单；没有执行请求清单。
- 此次也保留并通过旧 snapshot_sync 模式的测试；新版推荐使用 pr_diff_to_om.py，不需要运行旧模式。

---

## 先前版本验证记录

# 验证记录

2026-10-17，本次全套测试 **84 passed**：
- 原始转换/API mock/完整快照字段变化测试 55 项（包括 OM 1.12.0.0 官方生成模型校验）。
- 新增快照生命周期测试 29 项：有状态测试替身执行新增/修改/删除/恢复、表/列 rename、标注保留、外键循环、部分失败后重新规划、旧表保护、空快照、删除阈值、scope、分页、版本及计划变化、CLI plan/apply。

本地执行版本：Python 3.12，SQLGlot 27.29.0。默认安装仅使用 requirements.txt。没有安装完整 SDK 时，官方生成模型校验测试会自动跳过，其余 83 项可独立运行。

官方模型校验加载已安装 openmetadata-ingestion 1.12.0.0 的 generated.schema 模型；为避免未安装的 ingestion runtime 依赖引发初始化，它在测试进程中仅建立 metadata 包路径并直接加载生成模型。该处理没有写入产品运行代码，不代表整个 ingestion runtime 已通过集成测试。

参考源码核查：OM 1.12.0-release 的 EntityRepository.restorePatchAttributes、TableRepository、TableResource、DatabaseUtil。表 PATCH name 不具备实体 ID 保持的重命名语义，因此采用显式标注迁移与软删除。测试替身还模拟服务端的类型显示小写规范化和禁止重复主键表达规则。

未连接真实 MySQL/OM 服务。MySQL 仅做离线解析；OM HTTP 请求使用 mock，实际服务端兼容性和权限需要在部署版本的测试环境验证。未执行任何用户远端写操作。

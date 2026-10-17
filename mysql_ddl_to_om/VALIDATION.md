# 验证记录

2026-10-17，本次全套测试 **84 passed**：
- 原始转换/API mock/完整快照字段变化测试 55 项（包括 OM 1.12.0.0 官方生成模型校验）。
- 新增快照生命周期测试 29 项：有状态测试替身执行新增/修改/删除/恢复、表/列 rename、标注保留、外键循环、部分失败后重新规划、旧表保护、空快照、删除阈值、scope、分页、版本及计划变化、CLI plan/apply。

本地执行版本：Python 3.12，SQLGlot 27.29.0。默认安装仅使用 requirements.txt。没有安装完整 SDK 时，官方生成模型校验测试会自动跳过，其余 83 项可独立运行。

官方模型校验加载已安装 openmetadata-ingestion 1.12.0.0 的 generated.schema 模型；为避免未安装的 ingestion runtime 依赖引发初始化，它在测试进程中仅建立 metadata 包路径并直接加载生成模型。该处理没有写入产品运行代码，不代表整个 ingestion runtime 已通过集成测试。

参考源码核查：OM 1.12.0-release 的 EntityRepository.restorePatchAttributes、TableRepository、TableResource、DatabaseUtil。表 PATCH name 不具备实体 ID 保持的重命名语义，因此采用显式标注迁移与软删除。测试替身还模拟服务端的类型显示小写规范化和禁止重复主键表达规则。

未连接真实 MySQL/OM 服务。MySQL 仅做离线解析；OM HTTP 请求使用 mock，实际服务端兼容性和权限需要在部署版本的测试环境验证。未执行任何用户远端写操作。

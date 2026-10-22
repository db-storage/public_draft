**建议方案：独立 Okta 应用 `TemporalLocal` 负责 SSO；Okta 管理登录资格及组成员；Git 独立管理 Temporal 权限，通过已有流程同步到自部署集群。**

## 一、SSO：应用、用户、组分别负责什么？

当前 Temporal Cloud 的企业 SSO 使用 SAML；自部署 Temporal UI 原生支持 OIDC，可在同一个 Okta 租户中新建 `TemporalLocal` OIDC 应用，不必照搬 Cloud 的配置。

| 对象 | 作用 | 是否必需 |
|---|---|---|
| `TemporalLocal` Okta 应用 | 配置 Client ID、回调地址、登录策略等，供 UI 接入 SSO | 需要配置对应的 SSO 应用，建议独立创建 |
| 应用的用户分配 | 指定某个用户可以通过该应用登录 | 可以直接分配用户 |
| 应用的组分配 | 指定某个组的成员均可通过该应用登录 | 可选，可与用户直接分配同时使用 |
| AD 的 `RBAC_temporalLocal_user` 组 | 作为统一登录资格组 | **不必创建** |
| Token 的 `groups` claim | 向 Temporal 传递当前用户所属的相关组 | 使用 Okta 组进行授权映射时需要 |

**“把组分配给应用”只赋予组成员登录资格，不赋予 Temporal Namespace 权限。**将用户直接分配给应用，同样只解决登录资格。

另外，应用分配与 Token 的 groups claim 是独立配置：**分配组不会自动让 Token 携带组信息**，需要配置 claim 过滤器或 allowlist。

官方依据：

- [Temporal Cloud 访问管理](https://docs.temporal.io/cloud/manage-access)
- [自部署 UI OIDC 配置](https://github.com/temporalio/ui/blob/main/AUTHENTICATION.md)
- [Okta 应用用户/组分配](https://help.okta.com/en-us/Content/topics/apps/apps-configure-settings.htm)
- [Okta groups claim 配置](https://developer.okta.com/docs/guides/customize-tokens-groups-claim/main/)

## 二、是否继续使用 AD 的组？

员工账号可以继续来自企业 Active Directory，**但 TemporalLocal 的权限组不必建在 AD 中**。

| 选择 | 优势 | 劣势 |
|---|---|---|
| **在 Okta 创建 Local 权限组** | 无须修改 AD；Local 成员管理相对独立 | 需建立组负责人、成员审批和清理机制 |
| 使用 AD 来源的组 | 复用企业现有 AD 管理流程 | 依赖 AD 管理权限、同步及跨团队协调 |
| 不使用组，直接分配用户 | 配置简单，适合人数较少 | 人多后逐人维护成本较高 |

推荐独立 Local 应用，是为了隔离 Cloud 与 Local 的回调地址、客户端凭据和配置变更；**不是要求另建员工账号体系，也不是要求额外建立统一登录组。**

## 三、权限管理方案比较

你们已经具备：Local 独立 Git 权限文件、独立同步流程，以及可自定义的 ClaimMapper。因此以下方案都可实现。

| 方案 | Git 管什么 | Okta 管什么 | 优势 | 劣势 |
|---|---|---|---|---|
| **A：用户和组均可授权** | `user→权限`、`group→权限` | 登录资格、Okta 组成员 | 灵活，个人特殊授权方便 | 个人例外容易积累；退组后个人授权可能仍保留 |
| **B：仅通过 Okta 组授权，推荐** | `group→权限` | 登录资格、`user→group` | 人员变更集中在 Okta；Git 专注权限规则 | 审计需关联两处记录；需要管理权限组数量及负责人 |
| C：授权关系全部放 Git | `user→权限`，或逻辑组的成员及权限 | 登录资格、用户认证 | 授权配置统一走 PR，不依赖 Okta 组 | Git 承担人员成员关系维护；登录资格仍需在 Okta 管理 |

**日常采用 B；确有个人例外需求时，可采用 A，并限制个人授权期限。**如果要求所有人员授权变更都必须走 PR，则 C 更符合该治理目标。

## 四、推荐方案的具体流程

| 步骤 | 配置或行为 |
|---|---|
| 1．配置 SSO | 新建 `TemporalLocal` OIDC 应用，UI 配置对应的 Client ID、Secret、Issuer、回调地址 |
| 2．配置登录资格 | 将用户直接分配给应用，或将相关权限组分配给应用；两种方式可以混用 |
| 3．管理成员 | 例如 Alice 加入 Okta 组 `TemporalLocal_orders_operator` |
| 4．传递身份 | Token 返回可信用户标识，以及 Alice 所属的 Local 相关组 |
| 5．配置业务权限 | Git 定义 `TemporalLocal_orders_operator → orders Namespace: write` |
| 6．发布策略 | 独立流程将 Git 权限文件同步到 Local 集群并加载 |
| 7．执行授权 | 自定义 ClaimMapper 验证凭据、匹配策略、生成 Claims；Authorizer 检查每次 API 请求 |

## 五、代码依据与生效边界

基于此前检查的 Temporal Server **v1.32.1**：

| 组件 / 边界 | 结论 |
|---|---|
| [默认 ClaimMapper 源码](https://github.com/temporalio/temporal/blob/v1.32.1/common/authorization/default_jwt_claim_mapper.go) | 从 JWT 提取身份和权限；没有直接读取 Git 任意 user/group 映射的逻辑。你们可以自定义这部分 |
| [内置 Authorizer 源码](https://github.com/temporalio/temporal/blob/v1.32.1/common/authorization/default_authorizer.go) | 根据 Claims、目标 Namespace、API 所需角色判定权限；内置角色满足需求时，无须重写 |
| 登录成功但没有匹配权限 | 不授予业务操作权限，不能因为能登录就默认开放 Namespace |
| Git 权限变更 | 在同步、加载及相关缓存更新后生效，不必等待身份 Token 更新 |
| Okta 组成员变更 | 如果组信息来自 JWT，旧 Token 中的组不会自动变化，需明确刷新或失效时效 |
| Token 类型 | 确保 groups 位于 Frontend 实际验证的 Token 中；Okta org authorization server 支持 ID Token 的 groups，自定义 Access Token 的 groups 需 custom authorization server |

相关官方文档：

- [Temporal 自部署安全与授权扩展](https://docs.temporal.io/self-hosted-guide/security)
- [Okta groups claim 与 Token 类型](https://developer.okta.com/docs/guides/customize-tokens-groups-claim/main/)

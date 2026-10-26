## 带 JWT的authorize 


```mermaid
sequenceDiagram
    participant Client as UI Server / Temporal CLI
    participant FE as Temporal Frontend
    participant CM as ClaimMapper
    participant AZ as Authorizer

    Note over FE,AZ: ClaimMapper and Authorizer run inside Frontend

    Client->>FE: 1. gRPC metadata includes authorization = Bearer JWT
    FE->>CM: 2. Pass authentication information
    CM->>CM: 3. Validate JWT and map claims
    CM-->>FE: 4. Return Temporal Claims
    FE->>AZ: 5. Check roles for target API and Namespace
    AZ-->>FE: 6. Return allow or deny
    FE->>FE: 7. Execute or reject request
    FE-->>Client: 8. Return result or error
```


```mermaid
sequenceDiagram
    participant UI as UI Server
    participant CLI as Temporal CLI
    participant FE as Temporal Frontend
    participant CM as ClaimMapper
    participant AZ as Authorizer

    Note over FE,AZ: ClaimMapper and Authorizer run inside Frontend

    alt UI request
        UI->>FE: 1. gRPC metadata includes authorization = Bearer JWT
    else CLI request
        CLI->>FE: 1. gRPC metadata includes authorization = Bearer JWT
    end

    FE->>CM: 2. Pass authentication information
    CM->>CM: 3. Validate JWT and map claims
    CM-->>FE: 4. Return Temporal Claims
    FE->>AZ: 5. Check roles for target API and Namespace
    AZ-->>FE: 6. Return allow or deny
    FE->>FE: 7. Execute or reject request
```

## Terraform 流程
[temporalio/terraform-provider-temporalcloud](https://github.com/temporalio/terraform-provider-temporalcloud?utm_source=chatgpt.com)
MPL-2.0
```mermaid
flowchart LR
    User["Team Member"] -->|"1. Submit permission changes"| PR["Git Pull Request"]
    PR -->|"2. Review and merge"| Git["Git Repository"]
    Git -->|"3. Trigger CI pipeline"| Terraform["Terraform Plan / Apply"]
    Terraform -->|"4. Invoke provider"| Provider["Temporal Cloud Terraform Provider (Open Source)"]
    Provider -->|"5. Call Temporal Cloud API"| Cloud["Temporal Cloud: Account Roles and Namespace Permissions"]
```

```mermaid
flowchart TD
    User["Team Member"] -->|"1. Submit permission changes"| PR["Git Pull Request"]
    PR -->|"2. Review and merge"| Git["Git Repository"]
    Git -->|"3. Trigger CI pipeline"| Plan["Terraform Plan"]
    Plan -->|"4. Approve and apply"| Apply["Terraform Apply"]
    Apply --> Provider["Temporal Cloud Terraform Provider (Open Source)"]
    Provider -->|"5. Call Temporal Cloud API"| Cloud["Temporal Cloud"]
    Cloud --> Account["Account Roles"]
    Cloud --> Namespace["Namespace Permissions"]
```

## token 背景知识
- tokens returned from okta
```jsonc
{
  // Bearer: possession of the token is sufficient to use it; no private-key proof is required.
  "token_type": "Bearer",

  // Access token lifetime in seconds; does not describe ID token or refresh token expiry.
  "expires_in": 3600,

  // Granted scopes: openid = OIDC sign-in; profile = basic user details;
  // email = email address and verification status; offline_access = request refresh-token access.
  "scope": "openid profile email offline_access",

  // Token sent to the target API to authenticate requests and enforce granted permissions.
  "access_token": "...",

  // JWT containing identity claims, intended for the client that initiated sign-in.
  "id_token": "...",

  // Credential used by the helper to obtain new tokens without repeating interactive sign-in.
  "refresh_token": "..."
}
```
- example of access token
```jsonc
{
  // Issuer: the Okta authorization server that issued this token.
  "iss": "https://company.okta.com/oauth2/aus123",

  // Subject: identifies the authenticated user.
  "sub": "00u123example",

  // Audience: the API intended to accept this access token.
  "aud": "api://temporal",

  // Client ID: the OAuth application that requested this token.
  "cid": "temporal-cli-client-id",

  // Issued-at time: Unix timestamp in seconds.
  "iat": 1792886400,

  // Expiration time: Unix timestamp; this token expires one hour after issuance.
  "exp": 1792890000,

  // OAuth scopes granted to this access token.
  "scp": ["openid", "profile", "email", "offline_access"],

  // Custom claim: namespace permissions, explicitly configured in Okta.
  // Example format: "<namespace>:<role>"; must match the Temporal ClaimMapper.
  "permissions": ["dev:write", "prod:read"]
}
```

- example of id token 
```jsonc
{
  // Issuer: the Okta authorization server that issued this token.
  "iss": "https://company.okta.com/oauth2/aus123",

  // Subject: identifies the authenticated user.
  "sub": "00u123example",

  // Audience: the client that initiated sign-in, rather than the target API.
  "aud": "temporal-cli-client-id",

  // Issued-at time: Unix timestamp in seconds.
  "iat": 1792886400,

  // Expiration time: this ID token's own expiry, independent of access-token expiry.
  "exp": 1792890000,

  // User's display name; included here as an example profile claim.
  "name": "Alice Zhang",

  // User's email address; availability depends on scopes and claim configuration.
  "email": "alice@company.com",

  // Indicates whether the identity provider has verified the email address.
  "email_verified": true,

  // Optional custom claim: groups included through explicit Okta configuration.
  "groups": ["temporal-developers"]
}
```

### 总结下，感觉有多种方式
- 完全不关注Group，拿到user，自查表。 这种tf文件可以沿用当前格式，减少业务团队提交 PR的成本。自己搞个 terraform provider即可。
- JWT带 permission claim, 这需要有provider，自己的auth平台给okta转的。但是长度有些限制，一般也就是4k/8kb这种，因为放在grpc meta中，取链路中最小值. 当然也可以用*或者啥的
  例如：
  ```yaml
  {
  "iss": "https://company.okta.com/oauth2/default",
  "sub": "00u123abc",
  "aud": "temporal-frontend",
  "exp": 1793000000,
  "permissions": [
    "orders-dev:write",
    "orders-prod:read"
  ]
}```
- 使用JWT token的group信息，用组名规则，比如 namespaceA-read, namespaceA-admin。这有个问题：如果一个人能访问多个namespace，需要加入很多组。但是JWT是有长度限制的。
- 另外okta带的可能是role + permission，
- 使用group，但是不依赖于组名，也搞ACL映射表，ACL 映射表可以是多种，AI 还提到一个git作为source of truth的方式： 就是自己定义文件格式，FrontEnd直接去加载它。



(issuer, sub) 是用户的稳定身份标识；Authorizer 通常不需要用户名，只需要该用户已经解析出来的权限。
字段	含义	示例
iss（issuer）	哪个身份提供方签发了 token	https://company.okta.com/oauth2/default
sub（subject）	该签发方为用户分配的唯一标识	00u123abc
email / name	方便人识别的邮箱或姓名	alice@example.com / Alice


使用两者组合，是因为不同 issuer 可能出现相同的 sub；邮箱、用户名也可能修改。

例如 Okta 返回的 JWT 内容为：
{
  "iss": "https://company.okta.com/oauth2/default",
  "sub": "00u123abc",
  "email": "alice@example.com",
  "groups": ["temporal-orders-readers"]
}

鉴权过程是：
步骤	输入 → 结果
ClaimMapper 验证 token	确认这确实是可信 Okta 签发的有效 token
识别用户	(iss, sub) 标识该用户，email 用于展示和审计
解析权限	temporal-orders-readers → orders-prod: read
Authorizer 判断请求	请求读取 orders-prod → 允许；请求启动 Workflow → 拒绝


所以不是 Authorizer 拿用户名再查权限，而是 ClaimMapper 先把身份转换成权限，Authorizer 再判断权限是否允许当前操作。

如果你们要支持“直接给 Alice 授权”，数据库可以记录：
用户身份键	展示邮箱	Namespace	Role
(Okta issuer, 00u123abc)	alice@example.com	orders-prod	write


这时 ClaimMapper 根据 (iss, sub) 查询直接授权，再生成 Claims。用户名用于人看，稳定身份 ID 用于关联，角色权限用于鉴权。



# CLI 登陆新
目标是让员工通过 Okta 确认身份，再用 CLI 按权限访问自部署 Temporal。建议优先评估“浏览器登录获取 Access Token”，同时保留 mTLS 路线；不要把方案绑定在 `temporal cloud login` 上。

## 1. 需要解决的问题

| 问题 | 负责方 | 要完成什么 |
|---|---|---|
| 登录：用户是谁？ | Okta + 登录工具 | SSO / MFA、应用访问检查、签发凭据 |
| 认证：凭据是否可信？ | Temporal Frontend | 验证 JWT，或验证 mTLS 客户端证书 |
| 授权：允许做什么？ | ClaimMapper + Authorizer | 将身份映射为 Namespace 角色，并检查具体 API 操作 |

Okta 的“允许访问应用”不等于 Temporal 的“允许操作某个 Namespace”。

## 2. 候选方案比较

浏览器登录流程可以由独立辅助工具、企业已有工具或 CLI 扩展实现，Temporal CLI 负责执行业务命令。

| 方案 | 用户体验与适用场景 | 优点 | 成本与限制 |
|---|---|---|---|
| A. Authorization Code + PKCE | 本机 CLI 打开浏览器，登录后回到本机 callback | 适合开发者电脑；复用 Okta SSO/MFA；无需在 CLI 保存客户端密钥 | 需要登录工具；注册本地 callback；管理 Token 缓存和刷新 |
| B. Device Authorization | CLI 显示网址和验证码，用户在浏览器完成登录，CLI 轮询取得 Token | 适合 SSH、跳板机、无浏览器终端；不需要本地 callback | Okta 应用和策略须启用该授权类型；需要工具实现轮询 |
| C. mTLS 客户端证书 | 先取得个人证书，CLI 携带证书连接 | Temporal 明确支持；已有企业证书体系时容易融入 | 需要签发、轮换及撤销机制；服务端按证书身份映射权限 |
| D. 复用 Cloud CLI 登录实现 | 使用 OAuth profile，借用 `temporal cloud login` | 可能减少开发量，已有 PKCE、Token 保存和刷新代码 | 尚未完成真实 Okta 联调；不是明确记录的 self-hosted Okta 产品能力 |
| E. 手工取得 JWT，再传给 CLI | 手动获取 Token 后执行命令 | 适合快速验证 Frontend 认证授权 | 操作繁琐，Token 到期需处理，不适合作为长期员工入口 |

A、B 是 Okta 官方支持的 OAuth 流程，但不意味着 Temporal CLI 原生提供了对应的 Okta 登录入口。D 是 A 的一种实现候选，不是另一种认证协议。

参考：
- [Okta：Authorization Code + PKCE](https://developer.okta.com/docs/guides/implement-grant-type/authcodepkce/main/)
- [Okta：Device Authorization](https://developer.okta.com/docs/guides/device-authorization-grant/main/)

建议：先评估 A；若经常在 SSH/跳板机使用，则重点评估 B；公司已有成熟个人证书签发体系时，再将 C 放到同等优先级。

## 3. 推荐的 JWT 登录与授权流程

下面是 PKCE 方案设计图，不代表原生 Temporal CLI 已经完整支持该集成。

`Login Helper` 表示需要选型或实现的登录工具，也可以最终集成为 CLI 扩展。

```mermaid
sequenceDiagram
    participant C as Temporal CLI
    participant H as Login Helper
    participant B as Web Browser
    participant O as Okta
    participant F as Temporal Frontend

    H->>H: 1. Generate PKCE and state
    H->>H: 2. Start local callback
    H->>B: 3. Open authorization URL
    B->>O: 4. Send client_id, redirect_uri, scopes, state, challenge
    O->>O: 5. Authenticate user and check app access
    O-->>B: 6. Redirect with code and state
    B->>H: 7. Deliver code and state
    H->>H: 8. Validate state
    H->>O: 9. Exchange code with client_id, redirect_uri, verifier
    O-->>H: 10. Return tokens
    H->>H: 11. Store tokens
    H->>C: 12. Supply Access Token
    C->>F: 13. Call API with Bearer token and Namespace
    F->>F: 14. Validate JWT and map claims
    F->>F: 15. Check API and Namespace permissions
    F-->>C: 16. Return result
```

图中省略了部分协议参数：
- 授权请求还包含 `response_type=code`、`code_challenge_method=S256`。
- Token 兑换请求包含 `grant_type=authorization_code`。
- 请求 `openid` 时，成功响应还包含 ID Token；本方案使用 Access Token 访问 Temporal API。

Token 由本机登录工具/CLI 持有，这条路径不经过 Temporal UI Server。浏览器主要负责交互登录和传递授权码，Token 由登录工具直接向 Okta 兑换。

本地 callback，例如 `http://127.0.0.1:56628/callback`，需要在对应 Okta 应用中注册。浏览器和监听 callback 的登录工具应位于能够正确访问该 loopback 地址的同一台机器；远程终端场景可考虑 Device Authorization。

如果选 Device Authorization，主要替换图中 1–10 步：工具向 Okta 申请设备码，用户在浏览器确认，工具轮询 Token Endpoint；后续 Temporal 请求与授权过程相同。

参考：
- [Okta：PKCE 流程](https://developer.okta.com/docs/guides/implement-grant-type/authcodepkce/main/)
- [Okta：Device Authorization 流程](https://developer.okta.com/docs/guides/device-authorization-grant/main/)

## 4. 权限怎么设计

可以让 UI 和 CLI 使用独立的 Okta 应用，但共用面向 Temporal API 的 Token 签发策略和权限映射。

| 层次 | 建议配置 |
|---|---|
| Okta 应用 | CLI 使用 Native Application；分配允许使用的用户/组；配置 MFA、授权类型、callback |
| Token 签发 | 优先使用 Access Token；明确 Temporal API 的 audience；包含稳定用户标识及所需 groups / permissions |
| Frontend 认证 | 配置信任的签名密钥，并确保校验签名、有效期、issuer、audience；核对所选 ClaimMapper 的实际能力 |
| ClaimMapper | 若 Token 已符合默认 `permissions` 格式，可用默认实现；若传的是企业 groups，则实现 groups → Namespace 角色映射 |
| Authorizer | 优先复用内置角色授权器；特殊业务规则再考虑自定义 |
| 生命周期 | 登录工具处理缓存、刷新、重新登录；明确权限变更在 Token 有效期和权限缓存中的生效时间 |

一种适合企业维护的划分是：

- Okta 管理 `user → group`。
- Git / 权限服务管理 `group → Namespace role`。

这是方案建议，不是 Temporal 强制要求。

使用 Okta Access Token 保护自己的 Temporal API，需要使用适合自有 API 的 Custom Authorization Server；Org Authorization Server 的 Access Token 面向 Okta API。生产环境还应确认公司是否已有 API Access Management 授权。

参考：[Okta：Authorization Servers](https://developer.okta.com/docs/concepts/auth-servers/)

### Access Token 与 ID Token 的选择

- Access Token 面向 API，是本方案的优先选择。
- ID Token 面向 OIDC 客户端，用于证明登录身份；其 `aud` 通常是客户端的 `client_id`。
- Temporal UI 默认向 Frontend 转发 Access Token，可以通过 `TEMPORAL_AUTH_USE_ID_TOKEN_AS_BEARER=true` 改为 ID Token。
- 前面检查的 CLI OAuth 保存、刷新和请求路径使用 Access Token；如果选择 ID Token，需要额外适配。
- 无论选择哪种 Token，都要明确 audience、可信 issuer 和权限声明，不能通过关闭校验来解决配置不匹配。

参考：
- [Temporal UI 配置](https://docs.temporal.io/references/web-ui-configuration#providers)
- [Okta：Validate Access Tokens](https://developer.okta.com/docs/guides/validate-access-tokens/main/)
- [Okta：Validate ID Tokens](https://developer.okta.com/docs/guides/validate-id-tokens/main/)

## 5. 已确认的能力与尚未验证的部分

| 问题 | 结论 |
|---|---|
| 自部署 CLI 能否认证、授权？ | 能，有官方机制、示例和实际案例 |
| CLI 能否携带 JWT？ | 能，通过 `authorization` gRPC metadata 等方式 |
| CLI 能否使用 mTLS？ | 能，通过客户端证书与私钥连接 |
| JWT 是否必须配合 mTLS？ | 不必须；服务端可以接受 JWT + TLS，不要求客户端证书 |
| 是否必须先执行某个 `login` 命令？ | 不必须；已有有效 Token 或证书即可发请求 |
| 官方是否有明确的 self-hosted Okta 一键浏览器登录教程？ | 当前检索尚未找到，不能据此断言绝对不存在 |
| 能否复用 Cloud CLI 浏览器登录代码？ | 源码上有可复用路径，但未完成真实 Okta 联调 |
| 是否必须使用 Temporal UI Server 帮 CLI 登录？ | 不必须；PKCE / Device Authorization 可以由登录工具直接与 Okta 交互 |

### CLI 携带已有 JWT 的示例
[example](https://github.com/temporalio/temporal/issues/6664?utm_source=chatgpt.com)
[discussion](https://community.temporal.io/t/custom-headers-provider-for-temporal-cli/9362/2)


下面命令假设已通过登录工具获得 `JWT_TOKEN`：

```bash
temporal workflow list \
  --address temporal.internal.example:7233 \
  --namespace orders-prod \
  --tls \
  --grpc-meta "authorization=Bearer ${JWT_TOKEN}"
```

该命令负责携带 Token，不负责登录 Okta 或获取 Token。

### CLI 使用 mTLS 的示例

```bash
temporal workflow list \
  --address temporal.internal.example:7233 \
  --namespace orders-prod \
  --tls-cert-path ./user.crt \
  --tls-key-path ./user.key \
  --tls-ca-path ./server-ca.crt
```

证书签发由企业证书系统负责；证书身份对应的 Namespace 权限由服务端映射。mTLS 连接成功本身不等于完成 Namespace 授权。

## 6. 需要保留的文档与实际案例

| 来源 | 链接 | 能证明什么 |
|---|---|---|
| 官方文档 | [Self-hosted Security](https://docs.temporal.io/self-hosted-guide/security) | mTLS、JWT、ClaimMapper、Authorizer 的整体机制 |
| 官方参数 | [CLI Global Flags](https://docs.temporal.io/cli/command-reference/workflow#global-flags) | CLI 的 TLS 证书、私钥、CA、gRPC metadata 参数 |
| 官方示例 | [samples-server：TLS 完整示例](https://github.com/temporalio/samples-server/tree/main/tls/tls-full) | 自部署证书链及 CLI 访问示例，部分使用旧 `tctl` |
| 官方示例 | [samples-server：Authorizer](https://github.com/temporalio/samples-server/tree/main/extensibility/authorizer) | 现代 CLI 操作 Namespace，被授权器允许或拒绝 |
| 论坛讨论 | [How use authorization mechanism in worker](https://community.temporal.io/t/how-use-authorization-mechanism-in-worker/3613) | 用户成功通过 `tctl` 传递 JWT；维护者解释 Bearer Token 路径 |
| 论坛讨论 | [JWT token and mTLS switching](https://community.temporal.io/t/jwt-token-and-mtls-switching/3652) | CLI 使用 JWT、Worker 使用 mTLS 的配置讨论与成功反馈 |
| 实际案例 | [Temporal Issue #6664](https://github.com/temporalio/temporal/issues/6664) | 现代 CLI 使用 `--grpc-meta` 携带 JWT，成功创建 Namespace；其他操作遇到权限问题 |
| 官方 Cloud 文档 | [cloud login](https://docs.temporal.io/cli/command-reference/cloud/login) | Cloud 浏览器登录能力，不能直接当作 self-hosted Okta 支持承诺 |
| Okta 官方 | [Authorization Code + PKCE](https://developer.okta.com/docs/guides/implement-grant-type/authcodepkce/main/) | 本机浏览器登录获取 Token |
| Okta 官方 | [Device Authorization](https://developer.okta.com/docs/guides/device-authorization-grant/main/) | 无本地 callback 的交互登录 |
| Okta 官方 | [Authorization Servers](https://developer.okta.com/docs/concepts/auth-servers/) | Org 与 Custom Authorization Server 的用途边界 |

论坛和 Issue 提供的是具体使用证据，不能把旧版参数、个别部署经验直接当成当前版本的通用配置。


### 前面检查过的源码

以下链接固定到当时检查的提交，不代表所有已发布版本均具有相同行为。

| 源码 | 作用 |
|---|---|
| [cloud-cli：oauth.go](https://github.com/temporalio/cloud-cli/blob/91470346497871905eab8801f921da6a4289d173/temporalcloudcli/oauth.go) | 浏览器打开、PKCE、本地 callback、授权码兑换 |
| [cloud-cli：commands.login.go](https://github.com/temporalio/cloud-cli/blob/91470346497871905eab8801f921da6a4289d173/temporalcloudcli/commands.login.go) | 登录命令、默认 OAuth 地址生成、已有 profile 复用 |
| [cli：config.oauth.go](https://github.com/temporalio/cli/blob/5730c955d608c88bdc79de7910fe05a826cea314/cliext/config.oauth.go) | OAuth profile 的加载、保存及 Token 配置 |
| [cli：client.go](https://github.com/temporalio/cli/blob/5730c955d608c88bdc79de7910fe05a826cea314/cliext/client.go) | 普通 CLI 请求使用 Access Token，刷新后保存 |

复用这条实现时需要特别确认：
- 实际安装的 CLI 和 Cloud 扩展版本是否包含相应代码。
- Okta 的授权和 Token Endpoint 是否通过 profile 正确配置。
- scopes、audience、callback 是否与 Okta 应用和策略匹配。
- Token 保存和刷新是否符合企业要求。
- 不要将源码可复用等同于官方承诺的 self-hosted Okta 支持。

## 7. 建议的验证顺序

1. **先打通授权闭环**：获取一个测试用户 Token，让 CLI 携带它访问 Frontend，验证“允许读、拒绝写、拒绝访问其他 Namespace”。
2. **再验证登录体验**：本机测试 PKCE；远程终端测试 Device Authorization，比较公司 Okta 策略的兼容性。
3. **最后选择工具**：优先企业已有登录工具，其次评估现成 OAuth 工具或 Cloud CLI 代码复用，确有缺口再开发小型辅助工具。
4. **验证运维场景**：Token 过期刷新、退出、移除应用访问权、变更组成员、密钥轮换，以及 UI/CLI 权限是否一致。

这样可以先确认 Temporal 认证授权确实满足要求，再选择最适合员工使用的登录方式，避免先投入某个登录工具后才发现权限模型不匹配。

### 没有浏览器的场景
- 不带frontend的
```mermaid
sequenceDiagram
    actor User
    participant Helper as Login Helper on Remote Host
    participant Browser as Browser on User Device
    participant Okta

    User->>Helper: 1. Start login
    Helper->>Okta: 2. POST /device/authorize with client_id and scopes
    Okta-->>Helper: 3. Return device_code, user_code, verification_uri and interval
    Helper-->>User: 4. Display verification URL and user_code
    User->>Browser: 5. Open URL and enter user_code
    Browser->>Okta: 6. Complete login, MFA and device authorization
    Okta->>Okta: 7. Check app access and approve authorization

    loop Poll at the required interval until approved or expired
        Helper->>Okta: 8. POST /token with client_id, device_code and device grant_type
        Okta-->>Helper: 9. Return authorization_pending or tokens
    end

    Helper->>Helper: 10. Store tokens and supply Access Token to Temporal CLI
```

```mermaid
sequenceDiagram
    actor User
    participant Helper as Login Helper on Remote Host
    participant Browser as Browser on User Device
    participant Okta
    participant FE as Temporal Frontend

    User->>Helper: 1. Start login
    Helper->>Okta: 2. POST /device/authorize with client_id and scopes
    Okta-->>Helper: 3. Return device_code, user_code, verification_uri and interval
    Helper-->>User: 4. Display verification URL and user_code
    User->>Browser: 5. Open URL and enter user_code
    Browser->>Okta: 6. Complete login, MFA and device authorization
    Okta->>Okta: 7. Check app access and approve authorization

    loop Poll at the required interval until approved or expired
        Helper->>Okta: 8. POST /token with client_id, device_code and device grant_type
        Okta-->>Helper: 9. Return authorization_pending or tokens
    end

    Helper->>Helper: 10. Store tokens and supply Access Token to Temporal CLI
    Note over Helper,FE: The following request is sent by Temporal CLI on the remote host
    Helper->>FE: 11. Call API with Bearer token and target Namespace
    FE->>FE: 12. Validate JWT, map claims and check permissions
    FE-->>Helper: 13. Return result
```

# CLI 登陆和鉴权流程 （这个更早，不一定都对）
**对于你们的 self-hosted + Okta，浏览器登录可以实现，但需要配套登录工具。采用 CLI 本地回调的方案时，token 由本机登录工具获取、保存，再交给 Temporal CLI；UI Server 不参与。**

我读取了当前 CLI、UI Server 的源码及文档，有一个重要补充：**CLI 已有 OAuth Access Token 的读取、刷新逻辑，但不能据此认为它自带通用的 Okta 浏览器登录能力，更不能认为它会自动管理 ID Token。**

### 源码实际提供了什么

| 代码 | 核对结果 |
|---|---|
| CLI [`cliext/client.go`](https://github.com/temporalio/cli/blob/5730c955d608c88bdc79de7910fe05a826cea314/cliext/client.go) | 接收 gRPC metadata；读取 OAuth 配置；请求时返回 `AccessToken`，必要时刷新并保存 |
| CLI [`cliext/config.oauth.go`](https://github.com/temporalio/cli/blob/5730c955d608c88bdc79de7910fe05a826cea314/cliext/config.oauth.go) | 保存 access token、refresh token、过期时间和 OAuth 配置；没有专门保存 ID Token 的字段 |
| UI Server [`server/route/auth.go`](https://github.com/temporalio/ui-server/blob/9ba7e3c8b2c23a7dfc6597cc688ff0b5fe455f46/server/route/auth.go) | UI 登录回调由 UI Server 接收，并调用 `ExchangeCode` 兑换 token |
| UI Server [`server/auth/auth.go`](https://github.com/temporalio/ui-server/blob/9ba7e3c8b2c23a7dfc6597cc688ff0b5fe455f46/server/auth/auth.go) | UI 登录 token 会写入浏览器 Cookie；支持把 ID Token 替换为发往后端的 Bearer 凭据 |

以上是当前 `main` 的代码检查结果，**不保证你们安装的发行版已经包含全部能力**。官方文档中的 `temporal cloud login` 则属于 Cloud 扩展。

参考：[Use with Temporal Cloud](https://docs.temporal.io/cli/cloud)。

### 建议的 CLI 登录与鉴权流程

下面按你们倾向的 **ID Token** 画。图中的 **Login Helper 是需要复用或补充的本地工具，不是原生 `temporal login` 命令**。为控制图宽，Frontend 内部的 ClaimMapper、Authorizer 用自身调用表示。

```mermaid
sequenceDiagram
    participant H as Local Login Helper
    participant B as Browser
    participant O as Okta
    participant C as Temporal CLI
    participant F as Frontend Server

    H->>H: 1. Start loopback callback listener<br/>Generate state, nonce and PKCE verifier
    H->>B: 2. Open Okta authorization URL

    rect rgb(230, 240, 255)
        B->>O: 3. Authorize<br/>client_id, redirect_uri, scope=openid<br/>state, nonce, code_challenge
    end

    O->>O: 4. Authenticate user and MFA<br/>Check app assignment and policy
    O-->>B: 5. Redirect to registered loopback callback<br/>code + state
    B->>H: 6. Deliver code + state

    rect rgb(230, 240, 255)
        H->>O: 7. Exchange code for tokens<br/>client_id, redirect_uri, code_verifier
        O-->>H: 8. ID Token + Access Token<br/>Optional Refresh Token
    end

    H->>H: 9. Verify state and ID Token<br/>Validate signature, issuer, audience and nonce<br/>Cache credentials locally
    H->>C: 10. Run command with ID Token

    rect rgb(230, 240, 255)
        C->>F: 11. gRPC request over TLS<br/>authorization: Bearer ID_TOKEN
        F->>F: 12. ClaimMapper<br/>Verify token and map claims to namespace roles
        F->>F: 13. Authorizer<br/>Check roles against API and namespace
    end

    F->>F: 14. Execute API if allowed
    F-->>C: 15. Return result
```

PKCE 的 code 兑换由本地应用完成，Okta 返回 ID Token、Access Token，以及可选的 Refresh Token；浏览器在回调中通常传递的是 **code，不是最终 JWT**。

参考：[Okta Authorization Code with PKCE](https://developer.okta.com/docs/guides/implement-grant-type/authcodepkce/main/)。

### Token 到底由谁拿着？

| 场景 | 谁兑换 token | 谁保存 / 管理 | 请求经过 UI Server 吗？ |
|---|---|---|---|
| **CLI 本地回调方案** | 本机 Login Helper | 本机工具缓存，CLI 调用时取得 token | **不经过** |
| **Temporal UI 登录** | UI Server | 当前实现通过浏览器 Cookie 等管理登录状态 | 经过 |
| CLI 借用 UI 登录回调 | 需要专门实现安全交接 | 取决于自定义方案 | 非现成通用能力 |

**“浏览器参与登录”不意味着“必须经过 Temporal UI”。** 浏览器只是打开 Okta 登录页面；已经存在的 Okta SSO 会话可能让用户免输密码，但 UI 和 CLI 仍各自获取 token。

### 你们需要配置的关键点

| 位置 | 要配置什么 |
|---|---|
| Okta | 单独的 Native Application，例如 `TemporalLocalCLI`；启用 Authorization Code + PKCE |
| CLI 回调 | 注册本地回调，例如 `http://127.0.0.1:指定端口/callback`；必须满足 Okta 的 redirect URI 匹配规则，不能随意替换 UI callback |
| ID Token claims | 配置 `groups` 或 `permissions` |
| Frontend ClaimMapper | 信任正确 issuer / JWKS；明确允许 CLI 的 `client_id` 作为 ID Token audience |
| 权限 | 复用 UI 的 group 映射，或者读取 token 中的 Temporal `permissions` |
| 本地工具 | 完成登录、ID Token 验证、缓存、续期和 CLI 注入 |

**如果用 ID Token，就需要由 Login Helper 明确管理 ID Token 的更新。** 当前 CLI 的 OAuth 自动刷新路径使用的是 **Access Token**，不能直接拿来当作 ID Token 刷新方案。

最终发送请求可使用官方支持的 metadata 参数：

```bash
temporal workflow list \
  --address temporal.example.com:7233 \
  --namespace orders-prod \
  --tls \
  --grpc-meta "authorization=Bearer ${TEMPORAL_ID_TOKEN}"
```

`--grpc-meta` 是官方参数；上面的 `authorization=Bearer …` 是结合该参数格式与服务端 Bearer 要求得到的用法，**不是文档中原样提供的 Okta 登录示例**。服务端再执行 ClaimMapper → Authorizer。

参考：

- [Temporal CLI Global Flags](https://docs.temporal.io/cli/command-reference/env#global-flags)
- [Self-hosted Temporal Security](https://docs.temporal.io/self-hosted-guide/security)




## 问答

### ClaimMapper 把身份转成权限，参照什么转呢？


参照你们预先配置的“授权规则”转换。ClaimMapper 不会从身份本身推断出权限。

比如，你们在 Git 或权限数据库中维护：
主体类型	主体	Namespace	权限
Okta group	orders-developers	orders-dev	read, write
Okta group	orders-oncall	orders-prod	read
SPIFFE ID	spiffe://corp/orders-worker	orders-prod	worker
- 但是实际上考虑当前有多个domain，都允许它访问。那么可能就不好映射了。之前没有约定一定如何。


ClaimMapper 处理两类请求时：
请求	从已验证凭据中提取	查询上述规则	输出 Temporal Claims
Alice 通过 UI 操作	groups: ["orders-oncall"]	该组有生产订单 namespace 的读权限	orders-prod → RoleReader
订单 Worker 调用	spiffe://corp/orders-worker	该工作负载有 worker 权限	orders-prod → RoleWorker


随后 Authorizer 拿这些 Claims，与当前请求的 API 和 namespace 比较，决定允许还是拒绝。

因此三部分各有一个依据：
部分	依据什么
认证	Okta 签名 / SPIRE 证书，确认“你是谁”
ClaimMapper	你们维护的授权规则，得到“你有什么权限”
Authorizer	API 所需角色，判断“当前操作能不能执行”


另外，内置 JWT ClaimMapper 是另一种方式：它直接读取 token 中已经包含的 permissions，例如 orders-prod:read。你们如果只在 token 中放 Okta groups，就需要自定义 ClaimMapper，完成 group → namespace 权限 的查询与转换。


### 那对于工作负载,SPIFFE ID 怎么变换成role?


通过预先维护的 SPIFFE ID → namespace → role 授权规则，由自定义 ClaimMapper 查询并转换。SPIFFE ID 本身不包含 Temporal role。

例如，权限数据库中保存：
SPIFFE ID	Namespace	Roles
spiffe://corp/orders-worker	orders-prod	worker
spiffe://corp/orders-api	orders-prod	write
spiffe://corp/orders-api	orders-dev	read, write


以订单 Worker 为例：
步骤	具体动作
1. SDK 连接	使用 SPIRE 签发的 X.509-SVID 建立 mTLS 连接
2. Frontend 验证	TLS 层验证客户端证书链
3. ClaimMapper 提取身份	从已验证证书的 URI SAN 读取 spiffe://corp/orders-worker
4. 查询授权规则	用完整 SPIFFE ID 查询数据库或本地缓存
5. 构造 Claims	将 worker 转成 Temporal 的 RoleWorker
6. Authorizer 检查	判断当前 API、namespace 是否被这些角色允许


第 5 步的输出概念上是：
Claims{
    Subject: "spiffe://corp/orders-worker",
    Namespaces: map[string]Role{
        "orders-prod": RoleWorker,
    },
}

这条授权规则由你们的平台管理员配置，例如 Git PR → CI → 权限数据库；SPIRE 只负责签发和更新身份证明。即使某个服务拿到了合法的 SVID，如果授权表中没有对应规则，也应拒绝其业务请求。

不建议仅凭 ID 名称含有 worker 就自动赋予 worker 权限，应明确配置完整身份与权限的映射。


### ClaimMapper代码能区分请求来自于workload还是user么？

可以，但需要你们在自定义 ClaimMapper 中定义区分规则；Temporal 不会自动替你判断是人还是程序。

GetClaims(authInfo) 能获得两类信息：
输入	内容	可以识别什么
authInfo.AuthToken	gRPC 请求携带的 Bearer token	验证 Okta JWT 后识别用户
authInfo.TLSConnection	TLS 连接信息，包括客户端证书	从已验证证书的 URI SAN 识别 SPIFFE 工作负载


你们的方案中，UI Server 本身也是 workload，所以不能简单按“有证书就是程序、有 token 就是人”区分。 应结合可信调用方判断：
客户端证书身份	用户 token	按什么身份鉴权
指定的 UI Server SPIFFE ID	有效 Okta 用户 JWT	用户
指定的 UI Server SPIFFE ID	缺失或无效	拒绝
已授权的业务 SPIFFE ID	无	工作负载
业务 SPIFFE ID	有	按当前方案拒绝，避免身份混用


伪代码：
peerID := verifiedSPIFFEID(authInfo.TLSConnection)

if peerID == trustedUIServerID {
    user := verifyOktaUserToken(authInfo.AuthToken)
    return claimsForUser(user)
}

if authInfo.AuthToken != "" {
    return deny("unexpected token")
}

return claimsForWorkload(peerID)

这里的 verifyOktaUserToken 必须验证签名、issuer、audience 等，并确保是约定的用户 token。区分依据是经过验证的凭据及入口规则，不是请求中的用户名、SDK identity 或自报的 user/workload 字段。


```mermaid
sequenceDiagram
    actor User
    participant Browser as Web Browser
    participant UI as Temporal UI Server
    participant Okta

    User->>Browser: 1. Open Temporal UI
    Browser->>UI: 2. Sign in

    rect rgb(230, 240, 255)
        UI-->>Browser: 3. Redirect to Okta with client_id, redirect_uri, scope=openid, response_type=code, state
    end

    Browser->>Okta: 4. Request authorization with these parameters

    rect rgb(230, 240, 255)
        Okta->>Okta: 5. Authenticate user and check app access
    end

    Okta-->>Browser: 6. Redirect to callback with code + state
    Browser->>UI: 7. Send code + state to callback

    rect rgb(230, 240, 255)
        UI->>Okta: 8. Exchange code using client_id, client_secret, redirect_uri, grant_type=authorization_code
    end

    Okta-->>UI: 9. Return ID Token + Access Token
    UI->>UI: 10. Validate login response and establish session
    UI-->>Browser: 11. Set session cookie and open UI
```
配置位置	需要准备 / 配置
Okta	创建 OIDC Web Application，启用 Authorization Code
Okta	注册 UI 的回调地址 redirect_uri，为用户或 Group 分配应用访问权限
Temporal UI Server	TEMPORAL_AUTH_ENABLED=true
Temporal UI Server	TEMPORAL_AUTH_PROVIDER_URL：Okta 的 OIDC Issuer URL
Temporal UI Server	TEMPORAL_AUTH_CLIENT_ID、TEMPORAL_AUTH_CLIENT_SECRET：来自 Okta 应用
Temporal UI Server	TEMPORAL_AUTH_CALLBACK_URL：与 Okta 注册的 redirect_uri 一致
Temporal UI Server	TEMPORAL_AUTH_SCOPES：包含 openid，按需添加 profile,email

背景：当前公司使用temporal cloud，身份验证是基于okta，用了corp AD这个应用的RBAC_temporalCloud_user 做UI的身份验证，具体权限是通过git->terraform->temporal cloud同步的，支持按照user和group配置权限。后续希望自部署Temporal。
目的：我当前考虑自部署的情况下的human user management的权限问题。依然可以用okta。从UI登陆认证，希望用okta做sso。
问题1: 是搞个单独的okta应用，比如叫TemporalLocal，还是直接用corp AD这个应用的RBAC_temporalLocal_user?
问题2: 权限管理选择：1）全部在git配置？包括user和group权限都支持？2）git只管group的权限，然后okta管理user到group的关系？分别有什么好处？
要求：希望你的回答给予真实的文档和代码分析，然后简练一点，比如借助一些表格比较。


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

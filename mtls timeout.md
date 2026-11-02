**很可能是网络问题，但不能直接断定网络没有打通。** `net/http: TLS handshake timeout` 更准确的含义是：Temporal UI Server 在访问 Okta 的 OIDC Discovery Endpoint 时，**TLS 握手没有在规定时间内完成**。

尤其注意：这和 `connection timed out`、`connection refused` 不完全一样。

## 1. 可能的原因

| 原因 | 可能性 | 说明 |
|---|---|---|
| 网络策略、防火墙 | 高 | UI Pod 到 Okta 的 HTTPS 流量被阻断或中间设备丢包 |
| 企业 HTTP Proxy | 高 | 访问 Okta 需要代理，但 UI Server 没配置 `HTTPS_PROXY` |
| DNS 解析问题 | 中 | 域名解析到不可达 IP，或 IPv6 路径异常 |
| TLS 中间设备 | 中 | 企业网关、TLS Inspection、Service Mesh 导致握手卡住 |
| Okta Endpoint 响应慢 | 低～中 | Okta 或内部反向代理没有及时完成 TLS 握手 |
| 证书问题 | 相对低 | 证书不受信任一般报 `x509`，而不是握手超时 |

## 2. 建议直接在 UI Pod 内测试

假设你的 Okta URL 是：

```text
https://company.okta.com/oauth2/default
```

这里必须使用实际配置的 `TEMPORAL_AUTH_PROVIDER_URL`，因为 Temporal UI 会根据它进行 OIDC Discovery。

**第一步：测试 HTTPS 是否可访问**

```bash
curl -v --connect-timeout 5 --max-time 20 \
  https://company.okta.com/oauth2/default/.well-known/openid-configuration
```

观察输出：

| curl 结果 | 说明 |
|---|---|
| `Could not resolve host` | DNS 问题 |
| `Trying x.x.x.x...` 后超时 | TCP 连接可能未建立，检查网络策略 |
| `Connected to ...` 后 TLS 卡住 | TCP 已连接，重点检查 TLS、代理、网关 |
| `SSL certificate problem` | CA 证书或证书链问题 |
| HTTP 200，返回 JSON | 当前测试路径可访问，应进一步对比 UI Server 环境 |
| HTTP 403/404 | TLS 已完成，重点检查网关访问策略或 URL |

**第二步：检查 TLS 握手**

```bash
openssl s_client \
  -connect company.okta.com:443 \
  -servername company.okta.com
```

如果 TCP 已连接，但一直无法获得服务端证书，需要重点调查中间的网络设备、代理和 TLS 连接。

**第三步：检查代理配置**

```bash
env | grep -i proxy
```

重点看：

```bash
HTTPS_PROXY
HTTP_PROXY
NO_PROXY
```

如果你们公司访问 Okta 必须经过企业代理，而 UI Pod 没有配置 `HTTPS_PROXY`，就可能出现这类问题。

## 3. 重点检查一个细节

`TLS handshake timeout` 通常意味着 TCP 连接阶段已经完成，随后 TLS 握手超时。

例如：

```text
UI Pod
   │
   ├── DNS resolution         ✓
   │
   ├── TCP connection         ✓
   │
   ├── TLS handshake          ✗ timeout
   │
   └── HTTP GET               尚未执行
```

因此，**如果确认错误来自 Go 的 TLS 握手超时机制，排查重点不应只放在 TCP 443 端口是否开放，还应包括 TLS Inspection、代理、Service Mesh 和网络设备是否丢弃握手报文。**

Go 的 HTTP Transport 确实有独立的 `TLSHandshakeTimeout` 配置。

## 4. 我的建议

你是在 K8s 内部署 Temporal UI，对吧？我建议优先做两个测试：

```bash
# 1. 在 UI Pod 所在网络环境里测试
curl -v https://<okta-domain>/.well-known/openid-configuration

# 2. 检查 DNS 和 proxy
env | grep -i proxy
```

注意把第一条中的路径替换成实际 OIDC Discovery URL。

如果 UI Pod 因启动失败而无法进入，可以使用同 namespace、同网络策略条件的 Debug Pod 测试。普通 Debug Pod 的网络权限未必与 UI Pod 相同。

**我还想确认一点：你们的 Okta 是通过公网域名访问的（例如 `company.okta.com`），还是通过公司内部的 Private Endpoint / Proxy 访问？**

这会明显影响排查方向。

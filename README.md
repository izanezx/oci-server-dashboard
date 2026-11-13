# 多服务器监控中心（本机版）

本项目在 Mac 本机运行，使用 OCI CLI 只读查询已配置的实例；当前支持多台 OCI 实例。其他云厂商和家庭 PVE 接入尚未实现。Mac 休眠、关机或者程序退出时采集会停止；Oracle Monitoring 继续在云端保留其指标。未接入真实账号前不会显示模拟数据。

'https://github.com/jsongmax/oci-core'

## 启动

```sh
cd /Users/zhenxing.z/dev_projects/oracle/server-dashboard
python3 server.py
```

打开 <http://127.0.0.1:18765/>；保持运行窗口开启。仅绑定本机，不提供身份验证，不可直接对外开放。当前是前期本地验证，不是部署在 A1 或 PVE 上。浏览器读取 API 时需要主机名为 `localhost` 或 `127.0.0.1`。

## 认证说明

用户已确定长期使用 OCI API 签名密钥；完整操作见 [OCI 一次登录准备清单](OCI-SETUP.md)。下面临时会话仅保留为可选诊断方式，并非长期方案。

### 临时会话（可选诊断）

临时浏览器会话无需从控制台复制 Auth Token。你在自己的 Mac 终端运行：

```sh
oci session authenticate --region us-sanjose-1 --profile-name A1
```

在自动打开的 Oracle 页面自己登录并完成 MFA；在终端按实际提示完成。私钥、会话令牌和密码都不发送到聊天。会话一般一小时有效，且有刷新上限，适合人工验证，不适合长期无人值守采集。检查时运行：

```sh
oci session validate --profile A1 --auth security_token
```

要让以后迁移到 PVE 的看板长期采集，应新建专用的只读 IAM 身份及其 API 签名密钥，并授予受限范围的实例与监控读取权限；具体权限需按 tenancy 的 identity domain 和隔间结构配置、实测。私钥在运行看板的机器安全保存，勿提交 Git、复制进镜像或发给他人。OCI 控制台的 **Auth Token** 不是上述 CLI 会话令牌，也不是 API 签名私钥。

## 配置目标

在同一目录复制 `config.example.json` 为 `config.json`，在用户确认登录后填入区域、实例所在 compartment OCID 和 instance OCID；它们可从 OCI 控制台实例详情及隔间信息复制。临时登录使用 `"profile": "A1"`、`"auth": "security_token"`。API 密钥配置使用相应 profile 和 `"auth": "api_key"`。把 targets 数组复制条目可配置多台 OCI 实例。不要在 JSON 里填写密码、私钥或 Token。更改后重新启动程序。

程序每 5 分钟自动发现配置隔间及区域中的实例，从 `oci_computeagent` 查询最近 15 分钟、每分钟聚合的 CPU、内存、网络、磁盘指标；CPU 和内存图表另外查询最近 7 天、每小时聚合的数据。指标以云端最新时间戳标示；缺失数据不是零。网络/磁盘 rate 使用 OCI 的速率统计，指标名称和单位需实际账号接通后逐项比对 OCI 控制台；Oracle 文档不同段落对网络指标名称存在差异，若无数据应先查询指标定义而不是把它当作零。

## 开启 OCI 官方监控

1. OCI 控制台 → **Compute → Instances → A1 → Oracle Cloud Agent**，找到 **Compute Instance Monitoring**；检查是 Enabled 且运行状态是 RUNNING，两个状态需要分别确认。如果未运行，先检查 Agent 和出站连接；启停可能需要几分钟生效。
2. 实例详情 → **Metrics**，选择 `oci_computeagent`，查看 CPU、内存、网络与磁盘；时间范围选 7 天。采集从插件可用后开始，不保证恢复过去没发送的数据。Oracle 的查询分辨率与最大时间范围相关，例如 1 分钟分辨率最多查询 7 天，1 小时最多 90 天，具体请以控制台显示为准。
3. **Observability & Management → Monitoring → Alarm Definitions**：配置 CPU/内存阈值、指标缺失（absence）报警，目标设为 Notifications topic。指标缺失也可能是 Agent 或网络故障，不一定代表实例关闭；业务 URL 存活还需另配外部 HTTP 检测。
4. **Application Integration → Notifications** 新建 Topic、订阅邮箱，用户打开邮件完成确认。**Observability & Management → Events Service** 建立规则，选择 Compute 的 Instance Launch Begin/End、Instance Terminate Begin/End 等事件，动作选择 Notifications topic；按需要筛选隔间和实例。事件告知已发生的生命周期动作，不能保证提前预告闲置回收。后续可手动发一条测试消息，不能通过终止生产实例做测试。
5. 查看 OCI 账户的服务价格与免费额度再创建收费资源。Monitoring、Notifications 和公网出站分别有额度和计费细则，告警数量和频率也要核对。

## 账单与 10 TB

Oracle Always Free 文档称每月 10 TB 出站流量，按实际适用区域、服务、SKU 和账单核对。OCI Console → Billing & Cost Management → Cost Analysis，按日/月和服务、SKU、区域汇总 Usage / Cost；另在 Budgets 设置费用阈值和邮箱通知。Usage API 已接入本页面，按服务/SKU 等维度显示本月用量和费用，具有更新延迟和 IAM 权限要求。已查询到出站 SKU；免费额度的具体核算口径尚未完成核验，不显示剩余额度。各实例 `NetworksBytesOut` 不等于全租户计费出站。

## 迁移 PVE 前

准备专用只读身份、密钥安全存放、持久化配置、家庭网络访问保护、服务自启动和备份，并验证 PVE 能访问 OCI API。这个版本只监听本机，没有登录与加密功能，不应直接开放到家庭网络或互联网；迁移方案需另行完成并测试。

## 实际联调状态（2026-11-13）

已用现有 OCI_A1 身份只读验证：当前配置隔间内 A1、E2 均可发现，实例状态与监控插件状态为 RUNNING，CPU、内存、网络、磁盘 6 个指标均有近期数据；Usage 与 Cost 请求均成功，当前查询各未发现下一页。告警及事件规则读取成功但当前数量为零；Audit 可读，仅展示近 24 小时内匹配到的实例相关记录，不代表完整事件流。费用和用量内容不写本地日志。

用户组名称与租户的全资源管理策略匹配；由于使用现有用户，密钥可能具备广泛权限。已经验证的读取功能不需要新增 OCI 权限；对未来写操作并未执行改变资源的测试，不能保证全部成功。请勿将管理密钥视作只读。

尚未配置云端告警、Notifications、事件投递或外部 Webhook，也未验证通知链路、Oracle 闲置判定口径、10 TB 余额、跨隔间/多区域自动发现、多账户完整隔离、服务器管理写操作和 PVE 迁移。Usage API 可能延迟；查询最多显示 1000 条分组记录，结果达到上限时必须视为可能不完整。运行环境关闭时本地界面和采集停止。

## 七天历史查询修复（2026-11-13）

OCI 查询在只指定开始时间时，实测仅返回开始后的三个小时；现在所有指标查询显式设置开始和结束时间。A1 与 E2 的 CPU/内存各返回 168 个小时聚合点及 10079 个分钟聚合点。七天分钟级统计在内存中缓存一小时，降低 Monitoring 读取量；页面以一分钟均值计算 P95 作为参考，不等同 Oracle 对原始 CPU 的 P95 判定；内存显示分钟平均，网络利用率、实例规则适用性和 Oracle 最终判定仍未知。

## 动态指标图表（2026-11-13）

本地页面“实时指标趋势”展示 CPU、内存、网络上下行和磁盘读写，并叠加当前已发现的各实例。默认最近一小时；可选择 1、6、24 小时或 7 天，也可设置历史结束时间并一键恢复实时。每张图独立选择自动、1 分钟、5 分钟、1 小时、1 天间隔；CPU/内存可选均值、最小、最大、总和、计数、速率和 P50/P90/P95/P99/P99.9，网络/磁盘当前固定展示速率。鼠标悬停查看数值，表视图列出最近 200 条。

实时图表每 60 秒请求更新，后端相同查询缓存 45 秒；OCI 自身有采样和上报延迟，不能作为逐秒数据。七天范围选择 1 分钟会自动调整为 5 分钟，以控制读取量。每张图展示查询时间与实际采样间隔；数据缺失或查询错误不会显示为 0。计费/状态等原有面板仍按原有后台周期更新。

尚未实现截图中的复制图表 URL、复制 MQL、直接跳转 OCI 度量浏览器及从图表创建告警。历史查询受 OCI 数据保留、权限与时间范围限制；API 已验证真实账户结果，界面交互的本地模拟测试不能替代真实浏览器人工验收。

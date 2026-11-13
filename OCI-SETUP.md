# OCI 一次登录准备清单

更新：2026-11-12。此操作由用户自己完成。长期使用 OCI API 签名密钥，而非每小时过期的临时会话。

## 登录前的选择

API 签名密钥继承其所属 OCI 用户的 IAM 权限；如果给现有管理员账号添加密钥，该密钥可能具备管理员权限，即便看板目前只调用读取 API 也不能称为只读密钥。长期推荐为看板创建专用 IAM 用户、组和最小权限策略；未来需要写操作再分别规划授权。具体创建步骤会因 identity domain 配置而不同，需结合你的实际界面操作。若直接给现有账号添加密钥，必须理解其拥有该账号现有权限。

## 1. 登录 OCI，检查 A1

1. 用户自行登录 OCI 控制台，区域选择 `us-sanjose-1`（美国圣何塞）。
2. Compute → Instances → A1：记录或复制实例 OCID、所属 Compartment 名称；若容易找到，复制隔间 OCID。实例 OCID 以 `ocid1.instance...` 开头。若位于根隔间，可使用 tenancy OCID。
3. 实例页面 Oracle Cloud Agent → Compute Instance Monitoring：记录是否 Enabled、状态是否 RUNNING。若未运行先记录，不把它误报成正常。

## 2. 给选定的 OCI 身份添加 API 签名密钥

1. 在 OCI 控制台右上角的个人资料 → User settings / 我的个人资料；选择 API Keys / API 密钥。给专用身份配置时，在 Identity & Security → Domains → 对应域 → Users 中找到该用户，再打开其 API Keys；具体标签因控制台版本而异。
2. Add API Key → Generate API Key Pair → Download Private Key。私钥只留在自己的 Mac，不发送给任何人；不要下载后提交项目或通过聊天上传。
3. 点 Add 完成添加。控制台会显示 Configuration File Preview，包含 user、fingerprint、tenancy、region 和 key_file。请在自己电脑上的 `~/.oci/config` 添加一个新的 `[OCI_A1]` profile，粘贴预览内容并改名，不要覆盖已有其他 profile；把 region 填为 `us-sanjose-1`，`key_file` 指向实际私钥文件。预览中的 OCID/指纹不是私钥，但属于账户配置，建议直接留在本地。
4. 在 Mac 终端创建私钥目录并打开：`mkdir -p ~/.oci && chmod 700 ~/.oci && open ~/.oci`。在 Finder 将下载的私钥放进去；用终端 `chmod 600` 设置文件权限。配置文件同样应限本人读写。具体路径必须使用自己真实的文件名；不要输出私钥内容。
5. 如果使用独立 IAM 身份，还需赋予可访问账户、实例、OCI Monitoring 指标和告警，以及 Usage API 的权限。账单数据权限不同于实例权限；要访问费用而非仅 USAGE_ONLY，需核对 Oracle 所列报告权限。不要盲目授予 `manage all-resources`。控制台使用的是 API key，不是针对第三方兼容接口的 Auth Token。
6. 可在 Mac 用户终端执行 `oci iam region list --profile OCI_A1 --auth api_key`，只验证认证并可读访问；如果报错，请提供不含凭据的错误信息。后续应用按实际配置的 profile 查询实例与指标。

## 3. 告知助手的内容

- 是否已将长期 API Key 和 `[OCI_A1]` profile 安全配置到 Mac；**无需发送私钥、Token、MFA、密码或配置全文**。
- 使用的是现有 OCI 用户还是专用身份；专用身份若权限不足，提供界面上的脱敏权限错误。
- A1 的 Monitoring 插件 Enabled / RUNNING 状态。
- A1 的实例 OCID 和隔间名称/OCID：也可在授权本机只读发现后自动获取；无需在聊天发送，若手工提供，OCID 应视作内部标识，不要公开。

账户 PAYG、A1 区域、当前一个账户和本人内网使用已经确认，不需要再次提供。Webhook、PVE 信息与告警阈值后续再准备。

## 参考

- https://docs.oracle.com/en-us/iaas/Content/Identity/Tasks/managingcredentials.htm
- https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdkconfig.htm
- https://docs.oracle.com/en-us/iaas/Content/Billing/Concepts/costanalysisoverview.htm

## 用户提供的实例截图（2026-11-13）

- A1：`VM.Standard.A1.Flex`，截图显示 2 OCPU、12 GB 内存；区域 `us-sanjose-1`，位于根隔间。截图时状态为运行中。
- A1 的 Compute Instance Monitoring 插件截图显示已启用且正在运行；这不等于已确认过去 7 天指标完整。
- 同一实例列表还出现一台 E2 Micro（1 OCPU、1 GB），截图带“始终免费”标识。后续通过账户只读查询确认其区域、隔间及监控状态；目前不假设已纳入看板。
- A1 主 VNIC 截图中的网络安全组为无；这不说明子网安全列表或主机防火墙的具体规则。
- 截图没有显示 OCI API 密钥 Configuration File Preview；长期 CLI profile 仍待补充。不得将照片中按需容量类型或未显示 Always Free 徽标，单独作为 A1 计费或闲置回收规则适用性的证明。

## 本地接入验证（2026-11-13）

- 用户自行创建 API 密钥并下载私钥，指定使用现有 OCI 用户；本地私钥保存于 `~/.oci/oci-a1.pem`，权限仅限用户。
- 根据用户提供的本地配置预览创建 `~/.oci/config` 中的 `OCI_A1` profile；没有在日志或文档中记录密钥内容或完整账户标识。
- OCI API 只读查询区域成功，A1 状态读取为 RUNNING，最近一小时 CPU 指标查询返回 60 个数据点。
- 此结果证明上述只读操作可用；尚未验证用量/费用、其他监控指标、E2、多账户和看板整体验收。密钥继承现有 OCI 用户的权限，不能仅凭只读测试称其为只读凭据。

## 后续只读联调（2026-11-13）

本地 CLI 已成功读取当前隔间 A1/E2 的实例信息、监控指标、插件状态、OCI Usage/Cost、告警状态、事件规则、Audit 及根隔间 IAM 策略；当前用户组名称匹配全租户全资源管理策略。当前 0 个告警和 0 个事件规则是成功查询后的结果，不是权限故障；未创建新云资源。当前账单查询实测无后续页，流量 SKU 的单位为 GB Months，精确免费额度计算仍须核对。以上只验证读取，不证明所有未来写操作的权限或功能均已验收。

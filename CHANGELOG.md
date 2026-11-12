# Changelog

本项目的所有显著变更都记录在本文件中。
格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

## [0.1.2] - 2026-11-12

### 修复
- 列出服务器报错「'DescribeInstancesResponseBodyInstancesInstancePublicIpAddress' object is not iterable」：
  实例的公网 IP 与安全组 ID 均为 SDK 包装对象，需解包 `public_ip_address.ip_address` /
  `security_group_ids.security_group_id` 后使用；EIP 兜底逻辑保持不变
- 安全组规则查询改用 `max_results` + `next_token` 翻页（该接口无 `page_size` 参数）
- 新增基于真实 SDK 模型类的映射回归测试；已通过真实账号完成验证/列表/授权/撤销全链路实测

## [0.1.1] - 2026-11-12

### 修复
- 添加阿里云账号报错「object of type 'DescribeRegionsResponseBodyRegions' has no len()」：
  DescribeRegions 响应中 regions 为包装对象，需解包 `body.regions.region` 后使用
  （影响凭据在线验证与服务器列表的区域枚举两条路径）
- Release 说明自动提取时过滤 CHANGELOG 文末的链接引用定义行

## [0.1.0] - 2026-11-12

### 新增
- 阿里云 / 腾讯云 / 华为云账号绑定（AKSK + 在线验证，密钥仅存系统凭据服务）
- 服务器列表：覆盖云服务器与轻量应用服务器，自动枚举全部区域
- 针对当前公网 IP 的授权状态检测：已授权 / 未授权 / 授权过期
- 单台授权 / 取消授权；云厂商级「一键放行当前云厂商所有服务器」；跨账号「所有服务器一键授权」
- 授权标记：本系统创建的规则带 `CA|<账号短ID>|<IP>` 描述标记，可安全识别与清理
- 无边框浅色现代界面：侧栏搜索/添加账号、服务器表格、状态芯片、批量操作进度
- `--demo` 演示模式与 `--screenshot` 截图模式（离线，无凭据）

[未发布]: https://github.com/drank5090/CloudAccess/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/drank5090/CloudAccess/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/drank5090/CloudAccess/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/drank5090/CloudAccess/releases/tag/v0.1.0

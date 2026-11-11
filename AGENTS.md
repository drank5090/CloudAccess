# AGENTS.md — CloudAccess 智能体协作约束

本文件约束所有在本仓库工作的 AI 智能体与人类贡献者。任何变更（无论大小）都必须遵守。

## 项目概述

CloudAccess 是一个桌面工具：通过云厂商 AKSK 绑定多账号，列出云服务器与轻量应用服务器，
并针对"当前公网 IP"一键放通/撤销所有端口的防火墙规则。

- 语言/运行时：Python ≥3.11（锁文件基于 3.13），uv 管理依赖
- UI：PySide6，无边框浅色主题（QSS 常量见 `src/cloudaccess/ui/theme.py`）
- 打包：PyInstaller（CI 打 tag 时自动构建并发布到 GitHub Release）

## 支持范围

- 阿里云：ECS 安全组 + 轻量应用服务器(SWAS) 防火墙
- 腾讯云：CVM 安全组（VPC 模块）+ Lighthouse 轻量应用服务器防火墙
- 华为云：ECS/HECS 安全组（VPC v2 规则）

新增厂商时必须：实现 `providers/base.py` 接口 → 注册进 `providers/__init__.py` →
补 FakeProvider 单测与 `VENDOR_META` → 更新双语 README 的厂商表格。

## 硬性安全约束

1. **凭据零落盘、零入库**：源码、测试、示例、文档中禁止出现真实 AccessKeyId/SecretKey。
   演示/测试数据只能用 `demo-ak-0001` 这类明显占位。`tests/test_security_hygiene.py`
   会静态扫描违规字面量，CI 不容忽视其结果。
2. **凭据只存系统凭据服务**：AK/SK 经 `storage.SecretStore`（keyring）存取；元数据 JSON
   不允许包含凭据。任何新功能都不得把凭据写入日志、异常消息、截图或遥测。
3. **网络请求白名单**：对外 HTTP 仅限源码硬编码的 HTTPS 端点白名单（见 `iputil.py`），
   禁止把用户输入拼进 URL；新端点必须同步补充白名单测试。
4. **最小权限原则**：文档中引导用户使用只读+安全组管理权限的 RAM 子账号。

## 每次变更的工作流（必须完整执行）

1. 本地测试：`uv run ruff check src/ tests/ && uv run pytest`
2. UI 或演示数据有变化时，重新生成截图：`uv run python scripts/make_screenshots.py`
3. 更新 `CHANGELOG.md`（Keep a Changelog 格式，放在 `[未发布]` 段）
4. Git 提交：Conventional Commits（`feat:/fix:/docs:/chore:/ci:/test:`），
   一个逻辑变更一个提交，提交信息用英文、正文可中文
5. **版本发布**（重大功能或破坏性变更）：
   - 把 `[未发布]` 内容整理为 `[x.y.z] - YYYY-MM-DD` 段落
   - 同步 `pyproject.toml` 的 `version` 与 `src/cloudaccess/__init__.py` 的 `__version__`
   - `git tag vx.y.z && git push origin main --tags`，CI 自动测试→打包→发布 Release
   - Release 说明从 CHANGELOG 对应段落自动提取

## 代码规范

- Ruff（E/F/W/I/UP/B/SIM，line-length 100）；提交前必须零告警
- 厂商 SDK 调用只发生在 `providers/`；状态语义只发生在 `service.py`
- UI 不得直接调用厂商 SDK；所有阻塞调用必须走 `ui/asyncui.py` 的 `run_async`
- 注释/文档字符串用中文；标识符与提交信息用英文
- 测试：新增功能必须带单测；厂商 SDK 调用在测试中一律用 Fake 替身，禁止真实联网

## 文档规范

- README.md（中文）与 README.en.md（英文）必须同步更新，结构保持一致；
  截图统一引用 `docs/images/` 下的同一套图片
- 用户可见文案（UI、README 中文）使用中文；CHANGELOG 用中文

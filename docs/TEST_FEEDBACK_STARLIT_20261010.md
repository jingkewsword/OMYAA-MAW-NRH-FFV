# Electron 独立编辑器开发记录

日期：2026-10-10。维护者明确要求三项都做：同步 main、应用内更新、安装后直接打开独立编辑器。截图中的商业化讨论仅作背景，不实现定价、授权或售后条款。

## 基线与范围

- 从 upstream/merge/starlit-main 的 89775f6 建立独立 worktree 与 codex/starlit-desktop-updater 分支。
- 本轮 main 为 3a10baf；合并前 main 独有 36 个提交，桌面分支独有 26 个提交。
- 上轮三个更新包识别文件的改动先保存到命名 stash，合并完成后已恢复。
- 保留原工作区 WIP；维护者随后明确要求阶段性提交推送。当前认证账号 jingkewsword 对已改名的 fork jingkewsword/OMYAA-MAW-NRH-FFV 有 ADMIN 权限，使用本任务独立开发分支，不发布 Release、不修改定价。

| 项目 | 状态 | 处理与验证 |
| --- | --- | --- |
| main 合并 | 已修复 | bef52dd；解决 27 个冲突文件，保留 ESM 构建、桌面原生能力；定向 Node 36 项与 typecheck 通过，Python 475 项中三个失败修复后定向重测 3 项通过 |
| 安装后直接进入编辑器 | 已实现并编译 | Installer 改为编译期检查资源；安装完成、可选桌面快捷方式与工程关联直接进入 MOSE；实际安装包编译成功 |
| 应用内更新 | 已实现 | 独立 MOSE 清单和缓存、后台检查/下载/取消、哈希校验、未保存确认及安装交接；Windows 安装版可退出安装，其余包手动安装 |
| 分层验收 | 已通过主要检查 | Python 全量 1945 项通过（26 项跳过）、desktop Node 28 项、根目录 Node 497 项通过；实际打包 exe 的 Electron E2E 4/4 通过 |
| 商业模式 | 仅说明 | 抢先体验与最终开放是方向参考，不添加付费限制 |

## 验证边界

- 编辑器 bundle freshness 与 TypeScript 检查通过；未重生成 `blank-editor.html`，内联副本待发布前统一重生成。
- Python 初次完整回归中修复了新增模块未进入清单顺序断言的问题。最终按 Windows 发布流水线相同的 `PYTHONUTF8=1` 环境完整运行 1945 项，1919 项通过、26 项跳过，耗时 139.746 秒。一次遗漏 UTF-8 设置的中间复跑出现 GBK 解码错误，已确认是验证环境差异。
- PyInstaller 生成独立后端，Electron 44.1.0 / electron-builder 26.0.12 生成 Windows x64 MOSE.exe。打包版 4 项 E2E 全通过：取消退出、第二实例打开、后端清理；偏好跨重启；原生/拖入工程与保存；更新面板、权限隔离、说明转义、开关持久化。原生选择对话框由测试替身提供路径。
- 更新面板间距实测 16px；明暗主题截图位于 `build/desktop-qa-packaged/`。截图中的 99.0.0 和 HTML 字符串是转义测试数据，不是真实发布版本。
- 本机 electron-builder 解压签名工具中的 macOS 符号链接失败；将已下载归档的 Windows 工具解压到工作区缓存后成功构建，无需修改系统权限。没有配置发行签名证书。
- 本地后端按 MAW.spec 直接构建，未执行全套 ASR 托管 Runtime 冻结流程；本地包用于独立编辑器验收，不代表完整 Launcher 各识别引擎已验收。
- 未在用户系统执行安装/卸载、文件关联变更或真实跨版本更新。CI 安装测试脚本已补充 MOSE 快捷方式与直接打开命令检查，需隔离 Windows 环境实际运行。macOS/Linux 原生构建、签名/公证和实际更新未在本机验收。
- 发布流水线同时生成 MAW 与 MOSE 两份更新清单；已用明确标记为测试数据的五份资产运行生成器和 release.yml 中的实际校验脚本，两份清单通过校验。正式发布仍需上传真实资产与 MOSE 清单。本轮不创建 Release。
- `npm ci` 报告桌面现有依赖 17 个审计问题（1 moderate、15 high、1 critical）；本轮未升级既有 Electron/build 工具依赖或运行自动 audit fix，发行前需另行审计。

## 本地交付与提交

- 已推送主线合并 `bef52dd` 和功能实现 `782fe6b` 到 `jingkewsword/OMYAA-MAW-NRH-FFV` 的 `codex/starlit-desktop-updater` 分支；检查时没有该分支的远端 Actions 运行记录，以上验证为本机结果。
- 独立运行入口：`build/release/mose/MAW/MOSE/MOSE.exe`。需要保留完整 `MAW` 套件目录，不能单独复制此 exe。
- 安装包：`build/installer/MAW-Setup-Windows-x64-v1.8.0-beta.1.exe`，258,841,090 字节（246.85 MiB）。使用工作区内的 Inno Setup 6.3.1 编译成功，耗时 483.656 秒；正式 CI 使用 6.4.2，仍需在 CI 复核。
- 安装包 SHA-256：`8353d015160f3d0d0dd23ec816c122bf31c62046597fe066d9b8a511009aa19c`。
- 已为真实本地安装包生成 `build/installer/update-manifest.json` 与 `mose-update-manifest.json`，包含实测大小与 SHA-256；仅保留本地，不上传 Release。
- 构建/测试日志保留在 `build/qa-logs/`，打包界面截图在 `build/desktop-qa-packaged/`。本地产物和工具缓存位于忽略的 build/dist/node_modules 中，不进入源码提交。
- 此安装包是未签名的本地编辑器验证版，尚未执行真实安装和完整 ASR Runtime 验收，不标记为生产发行版。

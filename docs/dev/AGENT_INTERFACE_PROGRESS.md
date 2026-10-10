# Agent 接入实现记录

## 基线与设计

- 基线：main `3a10baf1`；独立分支 `feature/agent-interface`。
- 已核实：`.mosp` 是 UTF-8 JSON，schema 为 `moy.asr.project.v1`；时间为整数毫秒。复用 `maw.project` 校验、Qwen 转写/切句、浏览器字词协调与命令撤销。
- 现有 CLI 可转写文件，localhost API 可保存工程，但浏览器才持有未保存字幕、选区、撤销记录。没有现成的外部 Agent 编辑事务或范围重听写入口。
- 选择 JSON CLI + 文件提案桥：不新增服务或依赖 MCP 客户端。浏览器导出当前快照与选区；CLI 读取/查询、生成文本或范围替换提案、截取授权范围调用现有 Qwen；浏览器展示差异，重新检查基线后作为一次可撤销命令应用，沿用正常保存。CLI 不覆盖原工程。
- 范围为半开区间 `[start,end)`；跨边界字幕拒绝替换并返回需要的边界，避免默默扩大上传或改动范围。范围上下文只供查询，云端仅发送显式指定的 context 和截取音频。
- 结构替换对绑定副轨、分组装饰和帧模式等暂不支持的语义显式拒绝；文本修改保留元数据并使用既有字词协调算法。限制在用户文档中说明。
- 长任务使用调用进程 + 原子写出的任务状态文件，可由另一个 CLI 查询；不创建无人管理的后台服务。异常和中断记录失败，进程被强杀可能留下 running，提供明确诊断。
- MCP 后续可包装该命令契约；本次不手写另一个协议实现。

## 进度

| 项目 | 状态 | 证据 / 边界 |
| --- | --- | --- |
| 仓库与格式核对、隔离 | 已修复 | 原 checkout 干净；新 worktree 已创建 |
| CLI 查询、提案与范围转写 | 已修复 | 9 个 Python 测试通过，含真实 FFmpeg 800 ms 截取 + fixture 转写回填；未调用付费服务 |
| 编辑器快照、预览、冲突与撤销 | 已修复 | 2 个真实浏览器 e2e 通过；CLI → 导出/审阅/取消/应用/撤销/重做/保存/冲突；源码与 bundle 已更新 |
| Skill、接入文档、示例 | 待处理 | 仓库分发，不安装全局配置 |
| 测试与人工核验清单 | 待处理 | 区分 fixture、浏览器和真实云端验证 |

## 第一阶段验证

- `python -m unittest discover -s tests -p test_agent.py`：9 / 9 通过。
- `node --test tests/test_editor_script_syntax.mjs tests/test_editor_script_order.mjs tests/test_agent_editor.mjs tests/test_editor_commands.mjs`：15 / 15 通过。
- `pnpm run build:editor`、`pnpm run check:editor`、`pnpm run typecheck` 通过。
- `playwright test tests/e2e/agent-interface.spec.mjs --project=chromium --workers=1 --global-timeout=240000`：2 / 2 通过（20.3 秒），合成媒体及临时服务器已清理；对话框操作区实测间距 >= 8 px。
- 环境：新 worktree 无原 venv，创建独立测试 venv，安装所需依赖。沙箱 Python 临时目录与 pnpm realpath 曾因 Windows 权限失败，正常权限隔离运行通过；没有把这些失败计入产品缺陷。
- 后续要求：用户授权边开发边提交、推送到自己的 origin 功能分支；已实时核实登录与 push 权限。不合并 main、不创建 PR / Release。

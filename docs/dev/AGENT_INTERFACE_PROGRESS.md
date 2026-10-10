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
| Skill、接入文档、示例 | 已修复 | `.opencode/skill/maw-agent/SKILL.md`；按 skill-creator 校验通过；接入文档含可执行 PowerShell 示例 |
| 测试与人工核验清单 | 已修复 | 最终 Python 1878 项 OK（30 skipped）；JS 369 + 15 项通过；e2e 2 项通过；仓库外人工清单已生成，未代替人工勾选 |

## 第一阶段验证

- `python -m unittest discover -s tests -p test_agent.py`：9 / 9 通过。
- `node --test tests/test_editor_script_syntax.mjs tests/test_editor_script_order.mjs tests/test_agent_editor.mjs tests/test_editor_commands.mjs`：15 / 15 通过。
- `pnpm run build:editor`、`pnpm run check:editor`、`pnpm run typecheck` 通过。
- `playwright test tests/e2e/agent-interface.spec.mjs --project=chromium --workers=1 --global-timeout=240000`：2 / 2 通过（20.3 秒），合成媒体及临时服务器已清理；对话框操作区实测间距 >= 8 px。
- 环境：新 worktree 无原 venv，创建独立测试 venv，安装所需依赖。沙箱 Python 临时目录与 pnpm realpath 曾因 Windows 权限失败，正常权限隔离运行通过；没有把这些失败计入产品缺陷。
- 后续要求：用户授权边开发边提交、推送到自己的 origin 功能分支；已实时核实登录与 push 权限。不合并 main、不创建 PR / Release。

## 第二阶段验证与保存

- 首个可用实现提交 `bf092968` 已推送 origin/feature/agent-interface，并通过 `git ls-remote` 实时确认。
- CLI 增加 UTF-8 标准输出、非法非有限 JSON 拒绝、任务时间记录与状态写入失败提示；Agent Python 测试现为 10 / 10 通过。
- 原工程契约测试 49 / 49 通过；字幕 / 波形工具测试 369 / 369 通过；ruff 通过。
- Skill 校验需 Windows UTF-8 模式：`python -X utf8 <skill-creator>/scripts/quick_validate.py .opencode/skill/maw-agent` 通过。最初默认 GBK 解码失败，未更改技能内容来绕过编码。
- 旧 JS 工具测试默认执行 `uv run --frozen`，曾尝试重新创建测试 venv 并触发文件占用。改为显式 `MAW_TEST_PYTHON` 后全部通过；测试日志改放独立缓存目录。
- 全量 Python 首轮遇到 Windows GBK 子进程输出解码故障和停滞，已终止精确测试进程树；第二轮显式 UTF-8、固定解释器、240 秒封顶。待记录实际结果，不将首轮算作通过。
- 内联 `blank-editor.html` 按仓库约定待发布前统一重生成。

## 最终审查修正

- `buildJson({repair:false})` 提供无时间修复的序列化路径；导入/审阅/拒绝提案不再提前修复工程时间。导出快照仍显式提交输入并沿用保存规范化。
- 浏览器新增回归：人为制造未保存的异常时间后导入旧提案，冲突被拒绝且原时间不被提前修复。2 / 2 e2e 通过（9.9 秒）；截图已查看，审阅按钮区间距符合要求。
- 完整 Python 回归第二轮：1816 项，5 failures + 4 errors，30 skipped。其中 7 项关联缺少 `quapeaks`；2 项关联模块清单顺序/完整性。本次已补依赖并修正模块清单，未忽略失败。
- 针对修正后的 editor_assets / waveform / media_cache / quapeaks_generation / reapeaks 重跑 121 项，全部通过。

## 最终交付验证

- 完整 Python 回归：`python -X utf8 -m unittest discover -s tests -p test_*.py -v`，1878 项，`OK (skipped=30)`，103.605 秒，退出码 0。安装 quapeaks 后此前导入失败的模块参与实际执行，故数量增加。使用独立 venv、显式 UTF-8 与 240 秒超时，无真实付费请求。
- 最终 `check:editor` / `typecheck` / JS 语法、顺序、Agent 与命令测试（15 项）均通过；既有字幕/波形工具测试 369 项通过。
- Agent Python 专项 10 项通过，其中真实 FFmpeg + fixture ASR 测试通过；云端账号、上传、计费和识别质量未经实服务验证。
- 浏览器 e2e：2 项通过；覆盖真实 CLI 文件往返、主字幕选区、审阅取消、应用、撤销/重做、保存、范围外数据保留、审阅前后冲突以及拒绝时不修改时间。截图已视觉检查，操作区间距 >= 8px。
- Skill validator / ruff / `git diff --check` 通过。
- 人工清单按仓库模板生成在仓库外的 `../agent-interface-handoff-20261010/verification.html`，包含实际截图；人工项保持未勾选。
- 阶段代码提交 `bf092968`、`0d7c80d5`、`b88087d9` 已推送至用户 origin 功能分支。原 main 仍为 `3a10baf1` 且干净；未触碰另一个 docs worktree。
- 实现完成；未实施的范围：MCP 包装、实时浏览器会话接口、其他 ASR 引擎、打包 CLI 入口。明确限制：主轨、范围完整覆盖、结构替换不支持副轨绑定/装饰分组/帧模式，重听写不自动回填多说话人片段。

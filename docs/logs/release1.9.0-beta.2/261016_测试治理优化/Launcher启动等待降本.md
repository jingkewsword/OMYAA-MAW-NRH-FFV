# Launcher 交互测试的重复启动等待

维护者于 2026-10-16 授权继续处理剩余高成本测试，保留覆盖和断言、保持 PR #2 Draft 并更新说明。基线为 `b80aa2c4`，完整 CI [38909006687](https://github.com/jingkewsword/OMYAA-MAW-NRH-FFV/actions/runs/38909006687) 的 898/898 与 14 项检查已独立核对；这只是修改前的结果。上游 main 仍为已合入的 `fa5ae60c`，本阶段没有新的同步需求。

## 账本与取舍

| 候选 | 状态 | 当前证据与决定 |
| --- | --- | --- |
| Launcher 交互准备 | 已修复 | 最近完整 CI 按原始结果累加用例耗时为 152.211 秒，是最大的单文件。逐页静态 mock 初始化仍走 `waitForBackend` 的 1800ms 回退期限；原版 60/60；最终用现有 ready 事件结束已知无原生 API 的 mock 发现阶段，应用所有时钟保持原生，另保留一个原生 1800ms 回退旅程 |
| ASS 堆叠边界 | 仅说明 | 同样口径 115.164 秒，包含真实 libass/逐帧与时钟语义；当前没有证明可以删除的保障，不机械缩减 |
| 多字幕 / 波形历史 | 仅说明 | 分别 95.487 / 79.120 秒，涉及独立项目/服务和撤销生命周期；本轮不共享可变状态或删除原旅程 |
| 原集合、断言与故障检出 | 已修复 | 两版 60 项实际 ID、配置与零 skip/retry/flaky 完全一致；514 项原断言表达式 AST 完全不变。Node 原 20 个直接 test 定义不变，补一个 3.8ms 后端发现边界检查，27 项相关 Node 通过；两类故障均由断言检出 |
| 固定提交验收 | 仅说明 | 本地对照完成后仅常规推送现有分支，固定 head 的远端 CI 独立确认并更新 PR 说明；局部 A/B 不代替当前 head，保持 Draft，不合并或发布 |

累计用例时间含各用例的准备/清理，不是文件墙钟或 CPU 时间；不把跨文件并行耗时相加作为整套关键路径节省。原始报告与测量脚本留在忽略的 `.artifacts/phase11-cost/`。

## 保留边界

只处理测试准备，不修改真实 Launcher 的 1800ms 后端等待期限、生产功能、门禁选择、并发、超时、skip 或重试策略。启动完成后保留服务断开、迟到通知、设置保存、动画布局等原时序。静态 mock 不作为真实 pywebview/API、实际模型与正式发布包验收的替代。

## 最终实现与保留内容

仅 `launcher-interactions.spec.mjs` 内归并 34 处导航准备片段与一处 reload；进入静态浏览器页面后，由夹具派发实际 `pywebviewready` 事件。生产 `waitForBackend` 读取当前缺省 API 并进入原 mockApi，不替换其实现，不重写配置或 DOM 结果。没有 timer、Date、performance 或 requestAnimationFrame 替换，也没有生产开关、缓存可变应用状态或跨例复用 context。

`cloud ASR models show provider-specific price hints` 明确使用原生期限，不派发人工 ready；两版该用例 2.641 / 2.528 秒，回退路径仍在真实浏览器执行。其余后续的迟到通知、取消、断开重连、设置重载、复制反馈、动画布局等仍使用原生计时，全部原操作和结果断言保留。

新 Node 检查加载实际 `launcher-theme-bridge.js`，覆盖 API 已可用时立即返回、1800ms 无 API 回退、延后 ready 选取原生 API、无 API ready 选择 mock，以及较晚 timer / ready 不改变已完成结果。它用可控回调检查边界，真实墙钟回退另有上述原浏览器旅程。将期限误改为 0、把已有 API 错误返回 null 的两份忽略区源码变体分别由原比较断言检出，不能把 mock 快捷路径当成启动保障的替代。

## 单次对照与验收

| 项目 | 原版 | 最终版 |
| --- | --- | --- |
| 原 Chromium spec | 60/60，零 skip/retry/flaky | 同 60/60，零 skip/retry/flaky |
| Playwright 整轮耗时 | 185.503 秒 | 75.903 秒 |
| 有界运行器墙钟 | 186.14 秒 | 76.53 秒 |
| 原断言表达式 / ID / 配置 | 514 项 | 全部相同 |
| 原生回退代表用例 | 2.641 秒 | 2.528 秒 |
| 原取消旅程 | 3.717 秒 | 1.982 秒，原停止状态及不通知断言通过 |

两版均为同一机器、同配置、单 spec 一个实际 worker；本机还有其他工作负载。单样本约减少 109.6 秒（59.1%），不承诺固定比例、整套 CI 或 CPU/RSS / p95 收益。近期 CI 的 152.211 秒为累计用例时间，与这里的整轮墙钟口径不同，不混作 A/B。

完整 A/B 通过 `scripts/run_check.py --timeout 300 -- node node_modules/@playwright/test/cli.js test tests/e2e/launcher-interactions.spec.mjs --project chromium --forbid-only --reporter json`；相关 Node 使用 `node --test tests/test_launcher_feedback_ui.mjs tests/test_launcher_script_syntax.mjs`，27/27、零 skip，新增边界测试约 3.8ms。文档、个人路径与 diff 检查通过；原人工/API/模型及平台发布包边界不变。

## 弃用方案与真实失败

首个整页 Playwright Clock 候选为 59/60，不能算降本成功。取消状态的原断言真实失败，带事件记录的定向诊断再次检出；记录显示停止状态出现后约 200ms 即被迟到完成替换，整个页面的定时与动画模拟使观察窗口发生变化。没有增加重试、sleep、放宽停止断言或修改生产逻辑来迁就候选；直接弃用整页时钟替换。最终方案只改变静态 mock 的启动发现输入，恢复全部原生时钟后原 spec 60/60。失败与诊断仍保留在忽略区，不将首轮 59 项拼接成最终通过。

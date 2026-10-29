# 测试归组与夹具分层：第一批验收

基线：上游与 fork main `7e463fb4`；提取来源：fork PR 2 `292f1b0d`。最新 main 已包含 Python 分组、required/report、FFprobe 分层、缓存/HTTP/生命周期准备优化，本批只提取剩余差异。

| 范围 | 状态 | 结果 |
| --- | --- | --- |
| tone30 归组 | 已修复 | 30 分钟真实生成从 media 移至 long-media；两个短生成仍在 media，默认全集保留全部三项 |
| checksum 准备 | 已修复 | Bash 探测移至实际执行的 setUpClass；保留 60 秒上限，缺工具 required 仍失败 |
| Windows 原门禁 | 已修复 | 仅同步 tone30 精确用例 ID；同一次全量报告、缓存模块与零跳过要求保持 |
| Node 分组入口 | 仅说明 | 与第二批选测消费者一起交付；本批不新增过渡执行器 |
| 线上完整 CI | 待处理 | fork Draft PR 创建后验证其当前提交；本地结果不代表远端通过 |

本地执行：

```sh
python scripts/run_check.py --timeout 240 -- python scripts/run_tests.py tests/test_fixture_layers.py tests/test_windows_cache_gate.py tests/test_run_tests_runner.py tests/test_verify_sha256_script.py tests/test_reapeaks_fixture.py --required --report .artifacts/fixture-layers-ready.json
```

独立 Python 3.11 环境，NumPy 2.4.6、quapeaks 2026.0.0、真实 FFmpeg/FFprobe 与 Git Bash：37 项通过，零失败、错误或跳过，外层约 49 秒。首次使用缺 NumPy/可用 Bash 的环境时，required 如实失败；补齐独立环境后执行真实生成与工具测试，没有修改 skip 规则。

REAPER 比较 helper 与全部 10 个原方法的 AST 相同；类归属变化不修改原断言。新增两项回归在恢复旧源码后均失败（tone30 错归 media、导入启动 Bash），恢复新源码后通过。随后增加防止跨类重复生成的计数断言，最终分组与 Windows cache gate 3 项通过。原有 Windows 门禁正反用例继续拒绝缺 tone30、类/模块跳过、重复集合和空集合。

独立自审未发现阻塞问题：核对方法集合、实际 runner 的缺 Bash 类级 skip 拒绝、原报告接线；真实媒体执行由上述本地记录覆盖。没有删除原测试或引入第二批路径选测、第三批分片/汇总、APT 改动。

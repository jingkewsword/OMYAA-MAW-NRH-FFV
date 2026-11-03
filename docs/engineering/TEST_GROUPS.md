# 测试分组与夹具边界

Python 使用现有 `scripts/run_tests.py --pack <组> --required --report <文件>`。标准 unittest 发现完成后按用例归属筛选；默认无参数入口仍运行完整集合。`--required` 拒绝依赖、工具或夹具缺失导致的跳过，精确的平台不适用例外保持原规则。

| 组 | 负责的验证 |
| --- | --- |
| common | 常规算法、格式、状态、真实文件与 HTTP 契约；新增测试默认进入此组 |
| media | 真实 FFmpeg/FFprobe、媒体缓存和短媒体内核生成 |
| long-media | 30 分钟 tone30 内核生成与粗 mip 兼容、11 分钟音频对齐 |
| tools | 文档、发布、打包、执行器及维护工具 |
| manual | 需要维护者自有工程样例的历史场景；不能代替公开仓库的自动门禁 |

示例（先准备当前锁定依赖和所需 FFmpeg/FFprobe）：

```sh
python scripts/run_tests.py --pack media --required --report .artifacts/media.json
python scripts/run_tests.py --pack long-media --required --report .artifacts/long-media.json
```

冻结 REAPER 缓存解析仍在 common；短真实生成 tone_dual/tone_48k 在 media；30 分钟 tone30 在 long-media。三项生成继续使用同一比较方法和原断言。Windows 完整测试仍执行全部三项，并在同一次报告中拒绝漏项或跳过；分组不会缩减现有 CI 覆盖。

checksum 工具只在实际执行其测试类时准备 Bash。其他组的标准发现会导入测试模块，但不再因此启动 Bash。运行 tools 或默认全量时仍执行真实 checksum 脚本；Bash 缺失在 required 下仍失败。

当前尚未启用根据改动路径自动选组，也没有独立 Node 分组执行入口。Node/浏览器/进程测试继续使用已有命令和 CI；后续消费者映射与执行入口需一起交付。本指南不改变 CI 分片、结果汇总或分支保护。

# 通用短剧工作流维护入口

先读《工作流规则索引.md》。本目录集中维护六个Skill；各项目事实不可写入公共模板。更改先备份并做离线检查；不改线上项目，不花积分。历史备份不是当前执行规则。
维护任务再读 `maintenance/README.md`，先记录基线、Git 状态与文件范围，使用临时合成副本复现和验收。维护测试、手册和 CHANGELOG 保留；生产任务无需读取全部维护历史。只读诊断默认不落盘，不自动迁移真实项目、不刷新项目锁、不提交或推送 Git。

工作流身份由 `workflow.manifest.json`、直接子目录内的 `bundle.manifest.json` 和 `tools/workflow_paths.py` 共同核对；两个外层目录名可变。先运行只读 `python -B tools/workflow_paths.py doctor --json`，按资源 ID 解析所需文件。项目侧以自己的 `工作流绑定.json` 有界查找，版本差异须审查，不自动刷新锁。旧项目单项迁移命令见本目录 `README.md`。

# 通用短剧工作流

## 换电脑与经验继承

完整复制本公共目录，在新电脑运行 `python -B maintenance/portable.py install` 和 `python -B maintenance/portable.py check`，然后新开 Codex 对话。安装按本机位置写入全局短剧路由，保留原规则并自动备份；六个 Skill 仍维护一份。详见 [搬迁与安装](maintenance/搬迁与安装.md)。

已有剧必须连同自己的绑定、内容锁、剧本、素材和台账迁移，并执行只读项目检查；安装入口不会自动升级旧项目。路径诊断不代替平台登录、真实资产芯片和人物音频现场验收。2026-09-28 搬迁扩展保持规则 3.5.1 与定位合同 1.1.1，发布包以时间及内容哈希区分；本次 Skill/README 字节有更新，旧项目仍须显式审查锁差异。

本仓库维护可复用的 AI 短剧制作工作流（创作规则 **v3.7.0**、定位基础设施 **1.1.1**）：六个 Skill、项目模板、最终视频提示词排版规范，以及离线工具。公共文件只定义流程和字段含义；剧本、角色、主语言、真实素材名和制作进度由各短剧项目自己保存。

2026-10-01 G02升级：新项目默认20–30秒独立分镜、每实际镜头≤3秒、去完整资产名后每分镜≥2501汉字；B区生成控制实体全程完整绑定名，保护对白/画面文字原文。观看任务、视觉递进、末态和导演镜头账本成为必交合同，完整规则集中在[输出规范](视频提示词输出规范_资产全名版.md)。旧项目不自动修改参数、绑定或内容锁；迁移前审查资源差异与业务默认值，普通迁移仍保留旧业务值，需要明确配置新profile及记录用户覆盖。

整集校验使用 `JM-episode-check-v1`，含time_source整集绝对范围与segments数组（每段v2清单，逐段来源range_start/range_end连续覆盖整集，source_ref一致）。命令：`python -B tools/workflow_check.py 本集执行清单.json --prompt 本集.md --require-profile g02_cinematic_fullname_v2`。JSON输出quality_contract及warnings；v2无正文不能标记完成，v1仅保留单段历史诊断。静态PASS不证明导演语义、平台真实绑定或成片效果。

## 日常从这里开始

1. **开新剧**：告诉 Codex 新剧名和创建父目录，让它运行初始化并填写项目自己的启动说明/参数；公共母版不填单剧事实。
2. **继续制作**：打开那部剧的项目目录，让 Codex 先读项目入口、启动说明、参数、台账、绑定与锁，核对下一步和实际证据，再处理明确集段。
3. **检查或维护**：提示词使用下方单段检查器；公共文件异常先 doctor；修改公共工作流时读 [维护手册](maintenance/README.md)，备份、测试和归档。

用户通常只需看本 README 与项目自己的说明；定位、锁、初始化和维护源码交给 Codex 核对执行。台账中的已报告、已提交、待验收与已接受必须分清。文件读写不授予平台生成或费用权限。

## 更新说明（2026-09-26）

- 规则3.5.1将每个真实连续镜头改为0<时长≤3秒；按end-start判断，整集/生成段原定总长、已确认SRT、对白与声音事件时间保持。长内容用有动机的真实切镜覆盖，节拍标签不重置计时。
- 新项目从模板取得3秒；旧项目参数、绑定和版本锁不自动升级。普通迁移保留旧业务值，不能据此声称旧项目已符合3秒规则，须另有具体项目升级授权与差异审查。
- 清单和支持格式正文的静态检查共同采用3秒上限；实际生成视频须按真实切点另验，切点不明标记待人工确认。本次未操作平台或生成视频。

- 公共工作流和 Skill 包的外层目录可以改名或随工作区搬迁；固定清单与资源 ID 负责定位，重复或损坏的候选会明确报错。
- 新项目建立 `工作流绑定.json` 和按资源内容 SHA-256 核验的 v2 版本锁；旧项目须审阅单项目迁移计划后显式接入，内容差异不会自动接受。
- 新增 `maintenance/` 集中保留维护手册、测试、CHANGELOG、验收和备份。发布归档保留可复测源码，不包含报告、大备份、Git 或真实项目；当次基础设施更新保留六个 Skill 的创作规则与平台费用门禁；本次3.5.1仅按上述授权修改镜长规则。
- 1.1.1 补齐已发布 3.5 无 schema 物理锁与基础设施 1.0 默认项目入口的迁移；只认可有历史依据的默认路径与章节，同名自定义来源仍阻塞。原 1.1.0 包保留，具体复现与验收记录留在维护区。

## 从哪里开始

先读 [维护入口](AGENTS.md) 与 [工作流规则索引](工作流规则索引.md)。两个外层目录可改名；根目录 `workflow.manifest.json` 和包内 `bundle.manifest.json` 是固定身份标识。工具按资源 ID 解析文件，根 README 不直接链接可变包目录。

```powershell
python -B tools/workflow_paths.py doctor --json
python -B tools/workflow_paths.py list-resources --json
python -B tools/workflow_paths.py resolve skill.director --json
python -B tools/init_project.py --root '<新项目创建父目录>' --project-name '<新剧名>'
```

`--root` 只指定项目落点；公共目录默认由脚本自身位置定位，也可显式 `--common`。初始化先预检，建立项目 `工作流绑定.json` 与 v2 内容锁；已有旧项目须单独迁移，不通过重复初始化接受新版本。

从项目恢复时，先按项目 `工作流绑定.json` 的浅层 `search_roots` 只读查找固定标识；候选唯一且清单完整后，运行 `doctor --project '<项目目录>' --json`。`doctor` 不带项目只核对公共结构，不能表示该项目的内容锁通过。多份候选须明确 `--common`；内容哈希不同须先审查，不能自动刷新锁。

旧项目迁移或 v2→v2 内容升级只处理明确指定的一部剧；同版本无变化为 no-op，仅位置变化标为重绑定。未知规则或字段冲突阻塞。先运行 `python -B tools/migrate_workflow.py plan --project '<旧项目目录>' --common '<公共目录>' --output '<计划文件.json>'`，审阅旧锁映射、内容差异、拟修改控制文件与阻塞项；再用 `Get-FileHash -LiteralPath '<计划文件.json>' -Algorithm SHA256` 取得摘要，执行 `python -B tools/migrate_workflow.py apply --project '<旧项目目录>' --plan '<计划文件.json>' --approve-plan-sha256 '<摘要>'`。应用前会复核计划前置哈希，原控制文件备份留在该项目 `_workflow_migration_backups/`。不迁移剧本与素材的其他绝对路径。

## 六个 Skill

| 资源 ID | Skill | 主要职责 |
|---|---|---|
| `skill.prebreakdown` | screenplay-prebreakdown-analysis | 剧本事实、对白与旁白来源 |
| `skill.director` | ai-short-drama-director | 镜头任务、空间、连续性和导演判断 |
| `skill.acting` | cinematic-acting-execution-library | 可观察的表演写法 |
| `skill.compiler` | sd25-video-prompt-compiler | 时间预算、拆段与视频提示词内容编译 |
| `skill.adapter` | dreamina-sd25-prompt-adapter | 剧梦真实素材引用与内容适配 |
| `skill.production` | dreamina-short-drama-production | 平台制作范围、提交、验收和断点恢复 |

最终稿按 [视频提示词输出规范](视频提示词输出规范_资产全名版.md)排版。包内详细生产链可用 `resolve doc.bundle_readme` 定位。以上资源 ID 由本仓库工具解析，不是 Markdown 或 Codex 原生链接。

## 单生成段离线检查

先用 `python -B tools/workflow_paths.py resolve template.segment_check --json` 找到清单模板，根据当前项目来源填写。模板中的 `unknown` 和 `null` 表示尚未核对。

```powershell
python -B tools/workflow_check.py '<已填写的本段执行清单.json>' --prompt '<本段最终提示词.md>' --require-profile g02_cinematic_fullname_v2
```

[检查器](tools/workflow_check.py)仍可独立运行，只传清单时仅检查清单。静态检查不能证明实际视频切镜、音轨、文字拼写或平台真实引用绑定；成片须按实际结果验收。工作流本身不授权上传、生成或消耗积分。

## 维护与固定版本

```powershell
python -B maintenance/maintain.py check --json
python -B maintenance/maintain.py release --output-dir maintenance/releases --json
```

check 默认只输出；显式 `--report` 才写入维护 reports，零测试和必需跳过均失败。发布在临时冻结副本重新跑全测试、核对 ZIP 字节并解包冒烟，外置记录保存实际摘要。两个可变外层名称以外，固定入口和内部资源布局仍属于接口合同。

内容锁发现变化，但不会保留被覆盖的旧规则。长期制作应在明确获准位置展开某一发布包，按独立版本容器绑定项目；范围只覆盖选择的版本，不自动跟随 latest。本维护库更新会使仍绑定它的旧项目产生可见锁差异，需具体项目单独批准升级。本次不迁移真实项目，不刷新它们的锁，也不自动 Git commit/push。回退和故障处理见维护手册。

## 3.7 镜头语言升级

默认正式profile为g02_cinematic_fullname_v2，输出规范v1.4。整集设计摄影策略、每镜主动决定摄影机、每个相邻切点写双端承接，最终融入唯一B稿。六个Skill保持；新增资源reference.shot_language和tool.shot_language_check，无教程运行依赖。详见[专题规则](Codex适配剧梦/ai-short-drama-director/references/镜头语言选择与执行规则.md)。

完整离线样例：[固定合成输入](maintenance/tests/fixtures/shot-language/inputs.md)、[唯一完整Prompt](maintenance/tests/fixtures/shot-language/episode.md)、[内部清单](maintenance/tests/fixtures/shot-language/episode.json)、[逐镜语义审查](maintenance/tests/fixtures/shot-language/semantic_review.md)。运行 `python -B tools/workflow_check.py maintenance/tests/fixtures/shot-language/episode.json --prompt maintenance/tests/fixtures/shot-language/episode.md --require-profile g02_cinematic_fullname_v2`。样例只证明离线合同应用，不是生产资产或平台样片。

当前整集必须显式要求profile，并核对current_contract_passed与sequence_scope；历史诊断PASS和单段PASS均不能宣称本集完成。公共版本升级后，已有项目的锁会检测到规则差异，需要用户指定该项目后审查迁移，不能自动刷新。基础设施1.1.1、工作流身份和初始化/迁移算法保持。

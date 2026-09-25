# Codex 适配剧梦提示词库｜可复用模板

本模板把短剧剧本、项目资产、导演决策、SD2.5 Prompt 编译与剧梦平台操作连接为可恢复、可审计的生产流程。复制模板或阅读规范不自动授权打开线上项目、上传素材、生成视频或消耗积分。

## 六个 Skill

| 顺序 | Skill | 职责 |
|---|---|---|
| 1 | [screenplay-prebreakdown-analysis](screenplay-prebreakdown-analysis/SKILL.md) | 通读剧本与项目配置，建立事实、来源、人物知识、VO/OS、空间、素材候选和连续性输入。 |
| 2 | [ai-short-drama-director](ai-short-drama-director/SKILL.md) | 完成戏剧任务、知识差、视觉证据、镜头功能、空间连续性和导演验收。 |
| 3 | [cinematic-acting-execution-library](cinematic-acting-execution-library/SKILL.md) | 把已选定的导演意图转成可观察、可生成的表演语言。 |
| 4 | [sd25-video-prompt-compiler](sd25-video-prompt-compiler/SKILL.md) | 完成动态拆段、时间预算、风险与控制深度、Reference Authority 和五项内容职责；最终排版由独立规范负责。 |
| 5 | [dreamina-sd25-prompt-adapter](dreamina-sd25-prompt-adapter/SKILL.md) | 把执行稿适配到剧梦真实完整素材名、引用芯片、页面限制和生成前检查。 |
| 6 | [dreamina-short-drama-production](dreamina-short-drama-production/SKILL.md) | 编排任务重锚、平台操作、生成门禁、提交、Take 验收、日志和断点恢复。 |

三个长篇规范只作为对应 Skill 的按需参考，不再充当入口：

- [AI短剧导演核心规范_v3.4.md](ai-short-drama-director/references/AI短剧导演核心规范_v3.4.md)
- [视频模型工作流配置_SD2.5_v3.4.md](sd25-video-prompt-compiler/references/视频模型工作流配置_SD2.5_v3.4.md)
- [剧梦短剧制作总控_v3.4.md](dreamina-short-drama-production/references/剧梦短剧制作总控_v3.4.md)

## 快速开始

当前创作规则v3.5（2026-09-24）。先通过上级 `workflow.manifest.json` 和 `tools/workflow_paths.py` 定位《工作流规则索引.md》；本包外层目录名可变，包内相对链接仍有效。既有六个Skill及reference文件名保持兼容；文件正文的v3.5裁决为当前规则。

1. 通用工作流集中维护，新项目只保存参数副本、台账、AGENTS入口与版本锁，不再复制整套Skill；不要在母版中填写项目事实。
   六个 Skill 及 references 只保留跨项目流程、字段含义和校验方法；剧名、人物、对白、素材全名、主语言和项目路径都从当前项目文件与真实素材库读取，不使用其他项目的示例值。
2. 复制 [项目参数.template.json](dreamina-short-drama-production/assets/项目参数.template.json) 为项目自己的 `项目参数.json`，填写剧本来源、项目身份、资产映射、平台状态和授权范围。
3. 从 `dreamina-short-drama-production` 开始完整制作；只做单项工作时可直接调用对应 Skill。
4. 先完成事实预拆解，再做导演判断和 SD2.5 编译；剧梦适配只能使用平台真实存在且逐字一致的完整素材名称。
5. 没有线上或生成授权时，停在本地文件、生成准备或其他明确的可审计恢复点。

## 权威层级

| 层级 | 权威来源 | 负责内容 |
|---|---|---|
| L0 | 用户当前明确要求 | 本次范围、交付、临时要求、禁令和外部操作授权。 |
| L1 | 当前剧本、世界观、项目参数、真实素材和已接受 Sequence Canon | 作品身份、剧情事实、对白、角色实例、场景、道具、声音、画幅和连续性。 |
| L2 | `sd25-video-prompt-compiler` | 模型实现方式、动态拆段、时间预算、风险、控制深度、参考裁决和 Prompt。 |
| L3 | `ai-short-drama-director` | 戏剧理解、视觉证据、镜头功能、空间关系、表演方向和导演验收。 |

发生冲突时按 L0 → L1 → L2 → L3 仲裁。L2 和 L3 不得静默改写 L0/L1；平台总控也不替代创作和项目裁决。

## 素材名称与绑定

推荐使用半角下划线结构：

- 人物：`角色身份_场景或阶段_造型或状态_EP适用范围`
- 场景：`场景名称_场景形态_素材类型_EP适用范围`
- 顶视图：`场景名称_场景形态_顶视图站位图_EP编号`
- 道具：`道具名称_状态或用途_EP适用范围`

角色身份、角色实例和剧梦完整素材名称是三个不同字段。平台绑定键始终是剧梦素材库真实存在且逐字一致的完整名称；场景、顶视图和道具遵循同一原则。

## 标准生产链

事实预拆解 → 导演判断 → 表演语言细化（按需）→ SD2.5 编译 → 剧梦真实素材映射 → 单独引用 → 一键引用 → 页面实际状态验证 → 生成门禁 → 已授权提交 → Take 验收 → 接受后更新 Sequence Canon。

“本地 Prompt 已完成”“引用动作执行过”“生成已提交”和“成片已接受”是不同状态，必须分别记录。

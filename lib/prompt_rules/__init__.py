"""Prompt 规则单一真相源。

收录判据：跨多条 prompt 构建路径共享、且与具体视觉风格 / backend 无关的体裁或产品约束。
`episode_pacing` 是 drama / narration 的节奏建议（开篇钩子 / 中段冲突 / 末镜定格），正文存放在
`agent_runtime_profile/.claude/references/` 下，builder 与子智能体读同一个文件；
`episode_target_duration` 是三条脚本规划共享的单集目标时长措辞。`asset_identity_rules` 是
`analyze-assets` 子智能体抽取角色 / 场景 / 道具 description 时的身份锚定规则（肤色/发色/瞳色等
必写项、禁止清单、场景空间锚点、道具静态视觉口径），正文同样存放在
`agent_runtime_profile/.claude/references/` 下，子智能体 .md 与本模块读同一个文件。
`audience_gear` 是按受众
文本切换的创作规则块（目前只实现儿童 6-10 岁档位），供 drama 的 script_plan（normalize）与
prompt_authoring 共享。

属于"prompt 写作指导"而非可独立维护的规则文本的，写在
`lib/prompt_builders.py` / `lib/prompt_builders_script.py` 内部，不收进本包。
"""

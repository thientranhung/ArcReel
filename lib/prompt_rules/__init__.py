"""Prompt 规则单一真相源。

收录判据：跨多条 prompt 构建路径共享、且与具体视觉风格 / backend 无关的体裁或产品约束。
`episode_pacing` 是 drama / narration 的节奏建议（开篇钩子 / 中段冲突 / 末镜定格），正文存放在
`agent_runtime_profile/.claude/references/` 下，builder 与子智能体读同一个文件；
`episode_target_duration` 是三条脚本规划共享的单集目标时长措辞。`audience_gear` 是按受众
文本切换的创作规则块（目前只实现儿童 6-10 岁档位），供 drama 的 script_plan（normalize）与
prompt_authoring 共享。`shot_continuity` 是 drama / narration / 参考生视频三条 prompt_authoring
共享的 shot-to-shot 连续性与运镜规则（每分镜内部状态表、参考图只锁身份、表演纪律、运镜、
台词与声音口径），正文同样存放在 `agent_runtime_profile/.claude/references/` 下，子智能体
.md 与本模块读同一个文件。

属于"prompt 写作指导"而非可独立维护的规则文本的，写在
`lib/prompt_builders.py` / `lib/prompt_builders_script.py` 内部，不收进本包。
"""

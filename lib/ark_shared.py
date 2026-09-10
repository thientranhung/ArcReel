"""
Ark (火山方舟) 共享工具模块

供 text_backends / image_backends / video_backends / providers 复用。

包含：
- ARK_BASE_URL — 火山方舟 API 基础 URL
- resolve_ark_api_key — API Key 解析（缺失即 raise，不再走 env fallback）
- ark_base_url — 归一化用户输入（strip + 去尾斜杠），缺省回落 ARK_BASE_URL
- create_ark_client — Ark 客户端工厂
"""

from __future__ import annotations

ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


#: BytePlus ModelArk（火山方舟国际版）的 host 后缀。同一套 Ark 协议，但模型定名不同：
#: 国内站 ``doubao-seedance-2-5-260628`` 在 BytePlus 叫 ``dreamina-seedance-2-5-260628``，
#: 1.5 Pro 去掉 ``doubao-`` 前缀。registry 仍以国内站定名为唯一键（能力表 / 计费表都挂在上面），
#: 只在发往 BytePlus 的请求里换成对方认得的 ID。
BYTEPLUS_HOST_SUFFIX = "bytepluses.com"
_BYTEPLUS_SEEDANCE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("doubao-seedance-2-", "dreamina-seedance-2-"),
    ("doubao-seedance-2.", "dreamina-seedance-2."),
    ("doubao-seedance-1-5-pro", "seedance-1-5-pro"),
    ("doubao-seedance-1.5-pro", "seedance-1.5-pro"),
)


def is_byteplus_base_url(base_url: str | None) -> bool:
    """判断已归一化的 base_url 是否指向 BytePlus ModelArk。"""
    host = ark_base_url(base_url).split("://", 1)[-1].split("/", 1)[0].lower()
    return host == BYTEPLUS_HOST_SUFFIX or host.endswith("." + BYTEPLUS_HOST_SUFFIX)


def ark_api_model_name(model: str, base_url: str | None) -> str:
    """把 registry 模型键换算成目标站点认得的 API model ID。

    国内站原样返回；BytePlus 按前缀表换名，表外模型（Seedream、豆包文本等）原样透传——
    未核实的映射宁可让上游 404 报出真名，也不臆造。
    """
    if not is_byteplus_base_url(base_url):
        return model
    for src, dst in _BYTEPLUS_SEEDANCE_PREFIXES:
        if model.startswith(src):
            return dst + model[len(src) :]
    return model


def resolve_ark_api_key(api_key: str | None = None) -> str:
    if api_key is None or not api_key.strip():
        raise ValueError("请到系统配置页填写 Ark API Key")
    return api_key.strip()


def ark_base_url(configured: str | None = None) -> str:
    """归一化用户填入的 base_url：strip + 去尾斜杠，缺省回落 ARK_BASE_URL。

    不像 dashscope/minimax/agnes 那样按已知后缀做 host 派生再重建——ark 的 backend 会传入
    非标准变体路径（如 ark-agent-plan 用的 /api/plan/v3），按后缀重建会把这类路径拼坏，
    所以只做保守的空白/尾斜杠归一化，不改写路径结构。
    """
    # 先 strip 再判空：纯空白串（"   "）是真值会绕过 or，回落必须在 strip 之后。
    base = (configured or "").strip()
    return base.rstrip("/") if base else ARK_BASE_URL


def create_ark_client(*, api_key: str | None = None, base_url: str | None = None):
    """创建 Ark 客户端；base_url 缺省走 ARK_BASE_URL（即 /api/v3），经 ark_base_url 归一化。"""
    from volcenginesdkarkruntime import Ark

    return Ark(base_url=ark_base_url(base_url), api_key=resolve_ark_api_key(api_key))

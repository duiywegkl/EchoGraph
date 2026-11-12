"""OpenAI-compatible model listing and provider metadata normalization."""

from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests


UNKNOWN = "未提供（使用服务商默认）"


def validate_endpoint(base_url, api_key):
    base_url, api_key = base_url.strip(), api_key.strip()
    if not base_url:
        raise ValueError("接口地址不能为空")
    if not api_key:
        raise ValueError("API 密钥不能为空")
    try:
        url = urlsplit(base_url)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise ValueError
        _ = url.port
    except ValueError:
        raise ValueError("接口地址无效：请输入包含 http/https 和主机名的地址") from None
    return base_url.rstrip("/"), api_key


def _first(data, *paths):
    for path in paths:
        value = data
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value is not None and value != "":
            return value
    return None


def _flag(value):
    return UNKNOWN if value is None else ("支持" if value else "不支持")


def model_details(model):
    context = _first(model, "context_length", "context_window", "max_context_length",
                     "max_model_len", "top_provider.context_length", "max_input_tokens")
    output = _first(model, "max_output_tokens", "max_completion_tokens",
                    "top_provider.max_completion_tokens", "output_token_limit")
    modalities = _first(model, "architecture.input_modalities", "architecture.modality",
                        "modalities", "input_modalities")
    modalities = [modalities] if isinstance(modalities, str) else modalities
    vision = _first(model, "capabilities.vision", "supports_vision")
    if isinstance(modalities, list):
        has_image = any("image" in str(item).lower() for item in modalities)
        vision = (bool(vision) or has_image) if vision is not None else has_image
    parameters = model.get("supported_parameters")
    tools = _first(model, "capabilities.function_calling", "capabilities.tools",
                   "supports_tools", "supports_function_calling")
    reasoning = _first(model, "capabilities.reasoning")
    json_mode = _first(model, "capabilities.json_mode", "capabilities.structured_output",
                       "supports_json_mode", "supports_structured_output")
    if isinstance(parameters, list):
        if any(item in parameters for item in ("tools", "tool_choice")):
            tools = True
        if any(item in parameters for item in ("reasoning", "include_reasoning")):
            reasoning = True
        if any(item in parameters for item in ("response_format", "json_schema")):
            json_mode = True
    pricing = model.get("pricing")
    if isinstance(pricing, dict):
        price = ", ".join(f"{name}: {pricing[name]}" for name in ("prompt", "completion") if pricing.get(name) is not None) or UNKNOWN
    else:
        price = UNKNOWN
    created = model.get("created")
    if isinstance(created, (int, float)):
        try:
            created = datetime.fromtimestamp(created, timezone.utc).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            created = str(created)
    return {
        "上下文长度": str(context) if context is not None else UNKNOWN,
        "最大输出": str(output) if output is not None else UNKNOWN,
        "图片输入": _flag(vision),
        "工具调用": _flag(tools),
        "推理": _flag(reasoning),
        "JSON/结构化输出": _flag(json_mode),
        "提供方": str(model.get("owned_by") or UNKNOWN),
        "价格": price,
        "创建时间": str(created or UNKNOWN),
        "说明": str(model.get("description") or UNKNOWN),
    }


def parse_models(payload):
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("模型列表格式无效：需要 data 数组或模型数组")
    result = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"]:
            result[row["id"]] = row
    if not result:
        raise ValueError("模型列表为空或没有有效的模型 ID")
    return dict(sorted(result.items()))


def fetch_models(base_url, api_key, timeout):
    base_url, api_key = validate_endpoint(base_url, api_key)
    urls = [base_url + "/models"]
    if not base_url.endswith("/v1"):
        urls.append(base_url + "/v1/models")
    for index, url in enumerate(urls):
        try:
            response = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
        except requests.Timeout:
            raise ValueError("获取模型超时，请检查接口地址或请求超时设置") from None
        except requests.RequestException:
            raise ValueError("网络连接失败，请检查接口地址和网络") from None
        if response.status_code == 404 and index == 0 and len(urls) > 1:
            continue
        if response.status_code in (401, 403):
            raise ValueError("API 密钥无效或没有访问权限（HTTP %s）" % response.status_code)
        if response.status_code == 404:
            raise ValueError("接口不支持模型列表（HTTP 404）")
        if not response.ok:
            raise ValueError("获取模型失败（HTTP %s）" % response.status_code)
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("接口返回非 JSON 内容") from None
        return parse_models(payload), index == 1
    raise ValueError("接口不支持模型列表（HTTP 404）")

"""Per-kind node executors shared by the serial and parallel engines.

Each executor is a pure compute function: given the node payload and the
shared variable maps, it mutates variables and returns ``(output, delta)``
where ``output`` is the node's result string and ``delta`` is an optional
text snippet to emit as a node_delta event (the caller builds the event
with its own node id / title / kind).

Keeping one executor per kind means the serial and parallel engines share
the exact same node logic — no more drift between the two copies.
"""

from __future__ import annotations

from typing import Any, Callable

# main.py helpers are imported lazily inside each executor to avoid a
# circular import (main imports this module).


def _import_main():
    import main

    return main


def execute_code(node: Any, variables: dict[str, str]) -> tuple[str, str | None]:
    """code node: safe string operations (upper/lower/replace/concat)."""

    main = _import_main()
    output_variable = str(node.data.get("codeOutputVariable") or "code_output")
    output = main.run_safe_code_node(node, variables)
    variables[output_variable] = output
    return output, None


def execute_variable_assign(
    node: Any,
    variables: dict[str, str],
) -> tuple[str, str | None]:
    """variable_assign: render a template into a new variable."""

    main = _import_main()
    variable_name = str(node.data.get("variableName") or "assigned_text")
    template = str(node.data.get("template") or "")
    output = main.render_workflow_template(template, variables)
    variables[variable_name] = output
    return output, output


def execute_template_transform(
    node: Any,
    variables: dict[str, str],
) -> tuple[str, str | None]:
    """template_transform: render a long template into an output variable."""

    main = _import_main()
    output_variable = str(node.data.get("outputVariable") or "template_output")
    template = str(node.data.get("template") or "")
    output = main.render_workflow_template(template, variables)
    variables[output_variable] = output
    return output, output[:200]


def execute_variable_aggregator(
    node: Any,
    variables: dict[str, str],
) -> tuple[str, str | None]:
    """variable_aggregator: combine multiple variables into text or JSON."""

    import json

    main = _import_main()
    output_variable = str(node.data.get("outputVariable") or "aggregated_output")
    variable_names = main.split_workflow_variable_names(
        str(node.data.get("variableNames") or "")
    )
    output_template = str(node.data.get("outputTemplate") or "")
    values = {name: variables.get(name, "") for name in variable_names}
    if output_template:
        output = "".join(
            output_template.replace("{name}", name).replace("{value}", value)
            for name, value in values.items()
        )
    else:
        output = json.dumps(values, ensure_ascii=False)
    variables[output_variable] = output
    return output, output


def execute_list_operation(
    node: Any,
    variables: dict[str, str],
) -> tuple[str, str | None]:
    """list_operation: length/join/first/last over a comma-separated list."""

    main = _import_main()
    input_variable = str(node.data.get("inputVariable") or "user_input")
    operator = str(node.data.get("operator") or "length")
    output_variable = str(node.data.get("outputVariable") or "list_output")
    items = main.split_workflow_list(variables.get(input_variable, ""))
    if operator == "length":
        output = str(len(items))
    elif operator == "join":
        separator = str(node.data.get("joinSeparator") or "")
        output = separator.join(items)
    elif operator == "first":
        output = items[0] if items else ""
    elif operator == "last":
        output = items[-1] if items else ""
    else:
        raise ValueError(f"列表操作不支持：{operator}")
    variables[output_variable] = output
    return output, output


def execute_time_tool(
    node: Any,
    variables: dict[str, str],
) -> tuple[str, str | None]:
    """time_tool: now_iso / now_epoch / format."""

    from datetime import datetime
    import time

    output_variable = str(node.data.get("outputVariable") or "current_time")
    operation = str(node.data.get("operation") or "now_iso").strip()
    format_string = str(node.data.get("formatString") or "%Y-%m-%d %H:%M:%S")
    if operation == "now_iso":
        output = datetime.now().isoformat()
    elif operation == "now_epoch":
        output = str(int(time.time()))
    elif operation == "format":
        output = datetime.now().strftime(format_string)
    else:
        raise ValueError(f"时间工具操作不支持：{operation}")
    variables[output_variable] = output
    return output, output[:200]


_PURE_EXECUTORS: dict[str, Callable[[Any, dict[str, str]], tuple[str, str | None]]] = {
    "code": execute_code,
    "variable_assign": execute_variable_assign,
    "template_transform": execute_template_transform,
    "variable_aggregator": execute_variable_aggregator,
    "list_operation": execute_list_operation,
    "time_tool": execute_time_tool,
}


def run_pure_executor(
    kind: str,
    node: Any,
    variables: dict[str, str],
) -> tuple[str, str | None] | None:
    """Run a pure-compute executor; returns (output, delta) or None if unsupported."""

    executor = _PURE_EXECUTORS.get(kind)
    if executor is None:
        return None
    return executor(node, variables)


# ----------------------------------------------------------------------
# IO executors (async) — http_request / knowledge_retrieval /
# parameter_extractor / mcp_tool. These await external calls.
# ----------------------------------------------------------------------


async def execute_http_request(
    node: Any,
    variables: dict[str, str],
) -> tuple[str, str | None, str | None]:
    """http_request: GET/POST with outbound-gate or mock."""

    import json

    import httpx

    main = _import_main()
    method = str(node.data.get("method") or "GET").upper()
    url = main.render_workflow_template(str(node.data.get("url") or ""), variables)
    output_variable = str(node.data.get("outputVariable") or "http_output")
    headers: dict[str, str] = {}
    headers_json = str(node.data.get("headersJson") or "").strip()
    error_msg: str | None = None
    if headers_json:
        try:
            parsed_headers = json.loads(headers_json)
            if isinstance(parsed_headers, dict):
                headers = {str(k): str(v) for k, v in parsed_headers.items()}
        except ValueError as exc:
            error_msg = f"headersJson 解析失败：{exc}"
    body_variable = str(node.data.get("bodyVariable") or "").strip()
    body = variables.get(body_variable, "") if body_variable else None

    if not main.WORKFLOW_ALLOW_HTTP_OUTBOUND:
        output = (
            f"[http mock] method={method} url={url} status=200 body=mocked"
        )
        variables[output_variable] = output
        return output, f"outbound disabled\n{output}", error_msg

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.request(
            method,
            url,
            headers=headers,
            content=body if method == "POST" else None,
        )
    output = response.text
    if response.status_code < 200 or response.status_code >= 300:
        error_msg = f"HTTP 请求失败：{response.status_code}"
    else:
        variables[output_variable] = output
    return output, output, error_msg


async def execute_knowledge_retrieval(
    node: Any,
    variables: dict[str, str],
) -> tuple[str, str | None, str | None]:
    """knowledge_retrieval: query the local RAG service."""

    main = _import_main()
    output_variable = str(node.data.get("outputVariable") or "rag_context")
    query_variable = str(node.data.get("queryVariable") or "user_input")
    query_text = variables.get(query_variable, "")
    try:
        top_k = int(str(node.data.get("top_k") or "3"))
    except ValueError:
        top_k = 3
    top_k = max(1, min(top_k, 20))

    service = main.RagService(llm_enabled=False)
    knowledge_bases = service.list_knowledge_bases()
    if not knowledge_bases:
        variables[output_variable] = ""
        return "", "", "RAG 索引未就绪"

    kb_id = str(knowledge_bases[0]["id"])
    result = await service.query(kb_id, query_text, top_k=top_k)
    sources = result.get("sources")
    if isinstance(sources, list):
        parts = [
            str(source.get("text") or "")
            for source in sources
            if isinstance(source, dict) and source.get("text")
        ]
    else:
        parts = []
    output = "\n---\n".join(parts)
    variables[output_variable] = output
    return output, output or "RAG 未返回相关片段", None


async def execute_parameter_extractor(
    node: Any,
    variables: dict[str, str],
) -> tuple[str, str | None, str | None]:
    """parameter_extractor: LLM extracts JSON fields from text."""

    import json

    main = _import_main()
    output_variable = str(node.data.get("outputVariable") or "parameters_json")
    input_variable = str(node.data.get("inputVariable") or "user_input")
    schema = str(node.data.get("schema") or "")
    model_id = str(node.data.get("modelId") or main.TEXT_FALLBACK_MODEL)
    input_text = variables.get(input_variable, "")
    error_msg: str | None = None

    if not main.get_llm_gateway_config()[0]:
        output = "{}"
        variables[output_variable] = output
        return output, "LLM gateway not configured; returned {}", None

    prompt = (
        "请从以下文本中严格按 JSON 格式返回指定字段 "
        f"{schema}；若无法提取则返回空对象 {{}}。\n\n"
        f"文本：\n{input_text}"
    )
    raw_text = await main.collect_chat_completion_text(
        model_id,
        [main.ChatMessage(role="user", content=prompt)],
        temperature=0.3,
        max_tokens=1024,
    )
    json_text = main.extract_json_object_text(raw_text)
    if json_text:
        try:
            parsed = json.loads(json_text)
            output = json.dumps(parsed, ensure_ascii=False)
        except ValueError:
            output = raw_text
            error_msg = "参数提取 JSON 解析失败"
    else:
        output = raw_text
        error_msg = "参数提取未找到 JSON"
    variables[output_variable] = output
    return output, output, error_msg


async def execute_mcp_tool(
    node: Any,
    variables: dict[str, str],
) -> tuple[str, str | None, str | None]:
    """mcp_tool: call a registered MCP tool."""

    import json

    main = _import_main()
    output_variable = str(node.data.get("outputVariable") or "mcp_output")
    tool_name = str(node.data.get("toolName") or "").strip()
    error_msg: str | None = None

    if not main.WORKFLOW_MCP_TOOL_ENABLED or not tool_name:
        variables[output_variable] = ""
        return "", "mcp_tool 未启用或 toolName 为空", None

    registered_tools = await main.tool_registry.list_tools()
    matched_tool = next(
        (
            tool
            for tool in registered_tools
            if str(tool.get("name") or "") == tool_name
        ),
        None,
    )
    if not matched_tool:
        raise ValueError(f"MCP 工具未注册：{tool_name}")
    session_id = str(matched_tool.get("session_id") or "")
    raw_arguments = main.render_workflow_template(
        str(node.data.get("argumentsJson") or "{}"),
        variables,
    )
    arguments = json.loads(raw_arguments)
    if not isinstance(arguments, dict):
        raise ValueError("MCP 工具参数必须是 JSON 对象。")
    call_result = await main.mcp_manager.call_tool(
        session_id,
        tool_name,
        arguments,
    )
    text_parts: list[str] = []
    non_text_types: list[str] = []
    for part in getattr(call_result, "content", []) or []:
        if isinstance(part, dict):
            part_type = str(part.get("type") or "other")
            part_text = part.get("text")
        else:
            part_type = str(getattr(part, "type", "other"))
            part_text = getattr(part, "text", None)
        if part_type == "text":
            text_parts.append(str(part_text or ""))
        else:
            non_text_types.append(part_type)
    output = "\n".join(text_parts).strip()
    variables[output_variable] = output
    if non_text_types:
        error_msg = "非文本工具结果已省略：" + ", ".join(non_text_types)
    return output, output, error_msg


_IO_EXECUTORS = {
    "http_request": execute_http_request,
    "knowledge_retrieval": execute_knowledge_retrieval,
    "parameter_extractor": execute_parameter_extractor,
    "mcp_tool": execute_mcp_tool,
}


async def run_io_executor(
    kind: str,
    node: Any,
    variables: dict[str, str],
) -> tuple[str, str | None, str | None] | None:
    """Run an IO executor; returns (output, delta, error) or None if unsupported."""

    executor = _IO_EXECUTORS.get(kind)
    if executor is None:
        return None
    return await executor(node, variables)

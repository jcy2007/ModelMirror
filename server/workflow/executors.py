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


def execute_document_extractor(
    node: Any,
    variables: dict[str, str],
) -> tuple[str, str | None]:
    """document_extractor: read a file from a restricted root, preserving the
    output variable even on failure (setdefault, matches serial)."""

    main = _import_main()
    output_variable = str(node.data.get("outputVariable") or "document_text")
    source_path_variable = str(
        node.data.get("sourcePathVariable") or "document_path"
    )
    raw_path = variables.get(source_path_variable, "")
    root = main.workflow_document_extractor_root()
    candidate = (root / raw_path).resolve()
    output = ""

    if not raw_path.strip():
        error = "文档路径为空"
    elif root != candidate and root not in candidate.parents:
        error = "文档路径超出允许目录"
    elif not candidate.exists() or not candidate.is_file():
        error = "文档不存在"
    else:
        try:
            output = main.parse_document(candidate, candidate.name)
        except Exception:
            output = candidate.read_text(encoding="utf-8")
        variables[output_variable] = output
        # preserve output variable even on failure (setdefault)
        variables.setdefault(output_variable, output)
        return output, output[:500]

    variables.setdefault(output_variable, output)
    raise ValueError(error)


_PURE_EXECUTORS: dict[str, Callable[[Any, dict[str, str]], tuple[str, str | None]]] = {
    "code": execute_code,
    "variable_assign": execute_variable_assign,
    "template_transform": execute_template_transform,
    "variable_aggregator": execute_variable_aggregator,
    "list_operation": execute_list_operation,
    "time_tool": execute_time_tool,
    "document_extractor": execute_document_extractor,
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


async def execute_question_classifier(
    node: Any,
    variables: dict[str, str],
) -> tuple[str, str | None, str | None]:
    """question_classifier: keyword-rule classification with optional LLM fallback."""

    import json

    main = _import_main()
    output_variable = str(node.data.get("outputVariable") or "category")
    default_category = str(node.data.get("defaultCategory") or "未知")
    input_variable = str(node.data.get("inputVariable") or "user_input")
    categories_json = str(node.data.get("categories") or "{}")
    match_mode = str(node.data.get("matchMode") or "contains_any").strip()
    case_sensitive = str(node.data.get("caseSensitive") or "false").strip().lower() == "true"
    use_llm_fallback = str(node.data.get("useLlmFallback") or "false").strip().lower() == "true"
    model_id = str(node.data.get("modelId") or "").strip()
    text = variables.get(input_variable, "")

    # Respect the enable switch (matches serial engine).
    if not main.WORKFLOW_QUESTION_CLASSIFIER_ENABLED:
        variables[output_variable] = default_category
        return default_category, f"question_classifier disabled; default={default_category}", None

    raw_categories = json.loads(categories_json)
    if not isinstance(raw_categories, dict) or not raw_categories:
        raise ValueError("分类规则必须是非空 JSON 对象。")
    category_map: dict[str, list[str]] = {}
    for category_name, keywords in raw_categories.items():
        if not isinstance(category_name, str):
            raise ValueError("分类名称必须是字符串。")
        if not isinstance(keywords, list):
            raise ValueError("分类关键词必须是字符串数组。")
        clean_keywords = [
            str(keyword).strip()
            for keyword in keywords
            if isinstance(keyword, str) and keyword.strip()
        ]
        if not clean_keywords:
            raise ValueError(f"分类 {category_name} 至少需要一个关键词。")
        category_map[category_name] = clean_keywords

    comparison_text = text if case_sensitive else text.lower()
    selected = ""
    matched_keyword = ""
    for category_name, keywords in category_map.items():
        comparison_keywords = (
            keywords if case_sensitive else [keyword.lower() for keyword in keywords]
        )
        if match_mode == "contains_all":
            matched = all(keyword in comparison_text for keyword in comparison_keywords)
            keyword_hint = ",".join(keywords)
        else:
            hit_index = next(
                (
                    index
                    for index, keyword in enumerate(comparison_keywords)
                    if keyword in comparison_text
                ),
                -1,
            )
            matched = hit_index >= 0
            keyword_hint = keywords[hit_index] if hit_index >= 0 else ""
        if matched:
            selected = category_name
            matched_keyword = keyword_hint
            break

    delta_output = ""
    if selected:
        output = selected
        delta_output = f"已分类：{selected}（关键词命中：{matched_keyword}）"
    elif use_llm_fallback:
        if not main.get_llm_gateway_config()[0] or not model_id:
            raise ValueError("LLM 回退未配置网关或 modelId。")
        fallback_prompt = str(node.data.get("llmFallbackPrompt") or "").strip()
        if fallback_prompt:
            prompt = main.render_workflow_template(fallback_prompt, variables)
        else:
            prompt = (
                "请从下列文本中判断它属于哪个已知类别："
                f"{json.dumps(list(category_map.keys()), ensure_ascii=False)}。"
                "只回答类别名，不要多余文字或解释。如无法判断则回答 "
                '"未知"。\n\n文本：\n'
                f"{text}"
            )
        selected = (
            await main.collect_chat_completion_text(
                model_id,
                [main.ChatMessage(role="user", content=prompt)],
                temperature=0,
                max_tokens=20,
            )
        ).strip()
        output = selected or default_category
        delta_output = f"已分类：{output}（LLM 回退）"
    else:
        output = default_category
        delta_output = f"规则未命中，返回默认类别：{default_category}"

    variables[output_variable] = output
    return output, delta_output, None


async def execute_llm(
    node: Any,
    variables: dict[str, str],
    on_delta=None,
    on_status=None,
) -> tuple[str, str | None]:
    """llm: stream model output with retry/continue/fail strategy.

    ``on_delta(delta_text)`` is called for each streamed token so the caller
    can either collect (parallel) or yield (serial). ``on_status(text)`` is
    called for retry/error notices.
    Returns ``(output, error_message)``.
    """

    main = _import_main()
    model_id = str(node.data.get("modelId") or main.TEXT_FALLBACK_MODEL)
    prompt = main.render_workflow_template(
        str(node.data.get("prompt") or "{{user_input}}"),
        variables,
    )
    output_variable = str(node.data.get("outputVariable") or "llm_output")
    error_strategy = str(node.data.get("errorStrategy") or "fail").strip()
    try:
        retry_count = max(0, int(str(node.data.get("retryCount") or "1")))
    except ValueError:
        retry_count = 1

    attempt = 0
    while True:
        try:
            output = ""
            async for delta in main.stream_workflow_llm_text(model_id, prompt):
                output += delta
                if on_delta:
                    on_delta(delta)
            variables[output_variable] = output
            return output, None
        except Exception as exc:
            attempt += 1
            if error_strategy == "retry" and attempt <= retry_count:
                message = f"[重试 {attempt}/{retry_count}] {exc}"
                if on_status:
                    on_status(message)
                continue
            if error_strategy == "continue":
                variables[output_variable] = ""
                if on_status:
                    on_status(str(exc))
                return "", str(exc)
            raise


async def execute_agent(
    node: Any,
    variables: dict[str, str],
    on_status=None,
) -> tuple[str, str | None]:
    """agent: ReAct-Lite — direct answer or tool-first loop.

    ``on_status(text)`` reports progress (tool calls / direct-answer switch).
    Returns ``(output, error_message)``.
    """

    import json
    import re

    main = _import_main()
    output_variable = str(node.data.get("outputVariable") or "agent_output")
    output = ""
    if not main.WORKFLOW_AGENT_ENABLED:
        variables[output_variable] = output
        return output, "agent 节点当前未启用。"

    agent_mode = str(node.data.get("agentMode") or "tool_first").strip()
    model_id = str(node.data.get("modelId") or "").strip()
    instruction = main.render_workflow_template(
        str(node.data.get("instruction") or ""),
        variables,
    ).strip()
    prompt_suffix = main.render_workflow_template(
        str(node.data.get("promptSuffix") or ""),
        variables,
    ).strip()
    if prompt_suffix:
        instruction = f"{instruction}\n\n{prompt_suffix}".strip()
    if not model_id:
        raise ValueError("Agent 节点缺少 modelId。")
    if not instruction:
        raise ValueError("Agent 节点缺少 instruction。")
    try:
        temperature = float(str(node.data.get("temperature") or "0.7"))
    except ValueError:
        temperature = 0.7
    temperature = min(max(temperature, 0.0), 2.0)
    try:
        max_iterations = int(
            str(node.data.get("maxIterations") or main.WORKFLOW_AGENT_MAX_ITERATIONS_DEFAULT)
        )
    except ValueError:
        max_iterations = main.WORKFLOW_AGENT_MAX_ITERATIONS_DEFAULT
    max_iterations = min(max(max_iterations, 1), 20)

    async def run_direct_agent() -> str:
        if not main.get_llm_gateway_config()[0]:
            raise ValueError(main.LLM_GATEWAY_NOT_CONFIGURED_MESSAGE)
        return await main.collect_chat_completion_text(
            model_id,
            [main.ChatMessage(role="user", content=instruction)],
            temperature=temperature,
            max_tokens=main.WORKFLOW_AGENT_MAX_TOKENS,
        )

    if agent_mode == "direct":
        output = await run_direct_agent()
        variables[output_variable] = output
        return output, None

    if agent_mode != "tool_first":
        raise ValueError(f"Agent 模式不支持：{agent_mode}")

    registered_tools = await main.tool_registry.list_tools()
    requested_tool_names = [
        item.strip()
        for item in str(node.data.get("toolNames") or "").split(",")
        if item.strip()
    ]
    if requested_tool_names:
        allowed_names = set(requested_tool_names)
        available_tools = [
            tool
            for tool in registered_tools
            if str(tool.get("name") or "") in allowed_names
        ]
    else:
        available_tools = registered_tools

    if not available_tools:
        if on_status:
            on_status("Agent 切换为直接回答：没有可用 MCP 工具")
        output = await run_direct_agent()
        variables[output_variable] = output
        return output, None

    tool_by_name = {
        str(tool.get("name") or ""): tool
        for tool in available_tools
        if str(tool.get("name") or "")
    }
    tool_descriptions = "\n".join(
        (
            f"- {name}: "
            f"{tool.get('description') or '无描述'} "
            f"schema={json.dumps(tool.get('input_schema') or {}, ensure_ascii=False)}"
        )
        for name, tool in tool_by_name.items()
    )
    system_prompt = (
        "你是模镜工作流中的 ReAct-Lite Agent。"
        "你可以选择调用一个工具，或给出最终答案。"
        "每次回复必须是 JSON，且只能使用以下两种格式之一："
        '{"tool":"工具名","arguments":{...}} 或 {"answer":"最终答案"}。'
        "不要输出 JSON 以外的文字。\n\n可用工具：\n"
        f"{tool_descriptions}"
    )
    messages: list = [
        main.ChatMessage(role="system", content=system_prompt),
        main.ChatMessage(role="user", content=instruction),
    ]
    for iteration_index in range(max_iterations):
        if not main.get_llm_gateway_config()[0]:
            raise ValueError(main.LLM_GATEWAY_NOT_CONFIGURED_MESSAGE)
        raw_response = (
            await main.collect_chat_completion_text(
                model_id,
                messages,
                temperature=temperature,
                max_tokens=main.WORKFLOW_AGENT_MAX_TOKENS,
            )
        ).strip()
        json_text = raw_response
        fenced = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?```",
            raw_response,
            re.DOTALL,
        )
        if fenced:
            json_text = fenced.group(1).strip()
        try:
            decision = json.loads(json_text)
        except ValueError:
            output = raw_response
            break
        if not isinstance(decision, dict):
            output = raw_response
            break
        answer = decision.get("answer")
        if isinstance(answer, str) and answer.strip():
            output = answer.strip()
            break
        tool_name = str(decision.get("tool") or "").strip()
        arguments = decision.get("arguments")
        if not tool_name:
            output = raw_response
            break
        if not isinstance(arguments, dict):
            arguments = {}
        matched_tool = tool_by_name.get(tool_name)
        if not matched_tool:
            tool_result_text = f"工具不可用：{tool_name}"
            if on_status:
                on_status(tool_result_text)
        else:
            call_result = await main.mcp_manager.call_tool(
                str(matched_tool.get("session_id") or ""),
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
            tool_result_text = "\n".join(text_parts).strip()
            if non_text_types:
                tool_result_text = (
                    tool_result_text
                    + "\n"
                    + "非文本结果已省略："
                    + ", ".join(non_text_types)
                ).strip()
            if on_status:
                on_status(
                    f"[{iteration_index + 1}/{max_iterations}] "
                    f"调用工具 {tool_name}，结果预览：{tool_result_text[:300]}"
                )
        messages.append(
            main.ChatMessage(
                role="assistant",
                content=json.dumps(decision, ensure_ascii=False),
            )
        )
        messages.append(
            main.ChatMessage(
                role="user",
                content=(
                    f"工具 {tool_name} 的执行结果：\n"
                    f"{tool_result_text}\n\n"
                    "请继续用 JSON 决策下一步。"
                ),
            )
        )
    else:
        if on_status:
            on_status(f"Agent 达到最大循环次数 {max_iterations}，未得到最终答案。")
        output = ""
    variables[output_variable] = output
    return output, None


_IO_EXECUTORS = {
    "http_request": execute_http_request,
    "knowledge_retrieval": execute_knowledge_retrieval,
    "parameter_extractor": execute_parameter_extractor,
    "mcp_tool": execute_mcp_tool,
    "question_classifier": execute_question_classifier,
    "llm": execute_llm,
    "agent": execute_agent,
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

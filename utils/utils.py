"""
공통 유틸리티 함수 모음
"""

import json
import oracledb
from typing import List, Dict


def get_oracle_db_connection(user: str, pw: str, dsn: str):
    """
    Oracle DB에 접속 
    """
    conn = oracledb.connect(
        user=user,
        password=pw,
        dsn=dsn
    )
    return conn


def strip_code_block(text: str) -> str:
    """
    ```json ... ``` 또는 ``` ... ``` 감싼 부분 제거
    """
    if text.strip().startswith("```"):
        return "\n".join(line for line in text.strip().splitlines() if not line.strip().startswith("```"))
    return text


def clean_sql_query(raw_sql: str) -> str:
    """
    SQL 문자열에서 개행 문자와 세미콜론을 제거하고 한 줄로 정리
    """
    # 1. 개행 문자 제거 + 여러 공백을 하나로 압축
    one_liner = " ".join(raw_sql.strip().split())

    # 2. 끝에 세미콜론 제거
    return one_liner.rstrip(";")


def generate_tool_descriptions_for_ollama(tool) -> str:
    """
    Ollama LLM에게 전달(Prompt에 삽입)하기 위한, MCP 도구 관련 Description 생성
    """
    raw_schema = (
        getattr(tool, "inputSchema", None)
        or getattr(tool, "input_schema", None)
        or getattr(tool, "parameters", None)
    )

    props = {}
    required = []

    if isinstance(raw_schema, dict):
        props = raw_schema.get("properties", {})
        required = raw_schema.get("required", [])
    elif hasattr(raw_schema, "model_json_schema"):
        schema = raw_schema.model_json_schema()
        props = schema.get("properties", {})
        required = schema.get("required", [])
    elif isinstance(raw_schema, list):  # list of dicts
        props = {p["name"]: {"type": p["type"], "description": p.get("description", "")} for p in raw_schema}
        required = [p["name"] for p in raw_schema if p.get("required", True)]

    lines = [f"함수 이름: {tool.name}"]
    lines.append(f"설명: {getattr(tool, 'description', '')}")

    if props:
        lines.append("인자 설명:")
        for name, info in props.items():
            type_ = info.get("type", "unknown")
            desc = info.get("description", "")
            req = " (필수)" if name in required else " (선택)"
            lines.append(f"- {name} ({type_}){req}: {desc}")

    return "\n".join(lines)


def get_plan_tools_node_prompt(tool_descriptions: List[str]) -> str:
    """
    plan_tools 노드에 사용되는 MCP 도구 계획 프롬프트
    """
    return (
        "당신은 사용자의 자연어 질문을 해결하기 위해 MCP 도구를 활용하는 시스템입니다.\n"
        "아래는 사용 가능한 도구 목록입니다:\n\n"
        + "\n\n".join(tool_descriptions) +
        "\n\n이 중 필요한 도구만 선택하여 다음과 같은 JSON 배열 형식으로 반환하세요:\n"
        '''[
  {"function_name": "get_schema_info", "arguments": {}},
  {"function_name": "generate_sql", "arguments": {"natural_query": "...", "schema_info": "..." }},
  {"function_name": "validate_sql", "arguments": {"sql": "..." }},
  {"function_name": "execute_sql", "arguments": {"exec_sql": "..." }}
]'''
        "\n\n메모리 관련 도구 사용법:\n"
        "- 이전 대화를 조회하려면: get_messages()\n"
        "- 특정 키워드로 대화를 검색하려면: search_messages(keyword)\n"
        "- session_id는 자동으로 추가되므로 생략 가능합니다.\n\n"
        "만일, 선택된 도구가 없다면 사전에 학습한 지식을 바탕으로 사용자의 질문에 답변하세요."
    )


def get_generate_answer_node_prompt(executed_results: List[Dict]) -> str:
    """
    generate_answer 노드에 사용되는 최종 답변 생성 프롬프트
    """
    return (
        "다음은 MCP 도구 실행 결과입니다."
        "이를 종합해 사용자 질문에 대한 답변을 자연스럽게 작성하세요:\n\n"
        + json.dumps(executed_results, indent=2, ensure_ascii=False)
    )


def get_generate_sql_tool_prompt(natural_query: str, schema_info: str) -> str:
    """
    Oracle DB MCP 서버 - generate_sql 도구에서 사용되는 Text to SQL 프롬프트
    """
    return (
        "당신은 사용자의 자연어 질문을 oracle 쿼리로 변환하는 시스템입니다.\n"
        "아래의 DB Schema를 참고하여 사용자의 자연어 질문을 1개의 oracle 쿼리로 변환하세요.\n\n"
        "DB Schema:\n" + schema_info + "\n\n"
        "자연어 질문:\n" + natural_query + "\n\n"
        "불필요한 설명 없이 변환된 1개의 oracle 쿼리만 답변으로 반환하세요:\n"
    )
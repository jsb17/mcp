"""
공통 유틸리티 함수 모음
"""

import os
import re
import json
from pathlib import Path
from typing import List, Dict

from dotenv import load_dotenv


def strip_code_block(text: str) -> str:
    """
    ```json ... ``` 또는 ``` ... ``` 로 감싼 코드 블록의 내용만 추출
    코드 블록이 없으면 원문 반환
    """
    pattern = r"```(?:\w+)?\s*([\s\S]*?)\s*```"
    match = re.search(pattern, text.strip())
    if match:
        return match.group(1).strip()
    return text.strip()


def strip_think_block(text: str) -> str:
    """
    qwen 모델을 위한 별도 처리 함수 -  <think></think> 태그 제거
    """
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def generate_tool_descriptions_for_ollama(tool) -> str:
    """
    Ollama LLM에게 전달(Prompt에 삽입)하기 위한, MCP 도구 관련 Description 생성
    
    <형식>
    tool name: 도구 이름
    description: 도구 설명
    arguments: {파라미터: 파라미터 데이터 타입, ...}
    returns: 반환 결과 데이터 타입
    """
    load_dotenv() 
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    MCP_TOOLS_CONFIG_FILE_PATH = Path(os.path.join(BASE_DIR, os.getenv("MCP_TOOLS_CONFIG_FILE_PATH")))
    
    # MCP 서버 tool mapping 정보 로드
    if MCP_TOOLS_CONFIG_FILE_PATH.exists():
        with MCP_TOOLS_CONFIG_FILE_PATH.open("r", encoding="utf-8") as f:
            mcp_tools_config = json.load(f)
    tool_info = mcp_tools_config.get(tool.name, {"arguments": {}, "returns": "string"})
    
    # tool descriptions 생성 시작
    lines = [f"tool name: {tool.name}"]
    lines.append(f"description: {getattr(tool, 'description', '')}")
    
    # arguments 부분
    arguments = tool_info["arguments"]
    if arguments:
        arg_parts = [f"{name}: {type_}" for name, type_ in arguments.items()]
        lines.append(f"arguments: {{ {', '.join(arg_parts)} }}")
    else:
        lines.append("arguments: {}")
    
    # returns 부분
    lines.append(f"returns: {tool_info['returns']}")

    return "\n".join(lines)


def get_plan_tools_node_prompt(tool_descriptions: List[str]) -> str:
    """
    plan_tools 노드에 사용되는 MCP 도구 계획 프롬프트
    """
    return (
        "당신은 사용자의 자연어 질문을 해결하기 위해 MCP 도구를 활용하는 시스템입니다.\n"
        "아래는 사용 가능한 도구 목록입니다:\n\n" 
        + "\n\n".join(tool_descriptions) +
        "\n\n출력 규칙:\n"
        "1) 사용자의 요청을 해결하는 데 도구가 필요하다면, 아래 JSON 배열 형식으로만 출력하세요.\n"
        "  - 불필요한 도구 호출은 넣지 말고, 꼭 필요한 순서대로만 작성하세요.\n"
        "  - 예를 들어, 사용자의 질문이 데이터 조회 및 조인이라면, 반드시 아래의 구조 예시 순서대로 작성하세요!!!\n"
        "  - 구조 예시 (arguments 부분 중 모르겠는 부분은 '...'으로 처리하세요.):"
        """
        [
            {"function_name": "get_schema_info", "arguments": {}},
            {"function_name": "generate_sql", "arguments": {"natural_query": "...", "schema_info": "..." }},
            {"function_name": "validate_sql", "arguments": {"sql": "..." }},
            {"function_name": "execute_sql", "arguments": {"exec_sql": "..." }}
        ]\n"""
        "  - 각 항목: {'function_name': string, 'arguments': object}\n"
        "  - 최상위는 반드시 JSON 배열 하나여야 함. 추가 텍스트/주석/코드펜스 금지.\n\n"
        "2) 도구가 전혀 필요 없으면 JSON을 출력하지 말고, 일반 텍스트로 사용자의 질문에 대해 답변하세요.\n"
        "  - 이 경우 자연스럽고 완전한 문장으로 답변하세요.\n"
        "  - 절대 빈 배열([])이나 빈 문자열을 출력하지 마세요.\n"
        "  - 질문이 모호한 경우, 도구 호출 없이 일반 텍스트로 질문을 재확인하거나 추가 정보를 요청하세요.\n\n"
        "메모리 관련 도구 사용법:\n"
        "- 이전 대화 조회: get_messages()\n"
        "- 키워드 검색: search_messages(keyword)\n"
        "- session_id는 자동으로 추가되므로 생략 가능.\n\n"
        "주의:\n"
        "- JSON 형식 위반, 빈 배열, 빈 문자열은 허용되지 않습니다.\n"
        "- JSON과 텍스트를 동시에 출력하지 마세요. 둘 중 하나만 선택하세요.\n"   
    )


def get_generate_answer_node_prompt(question: str, executed_results: List[Dict]) -> str:
    """
    generate_answer 노드에 사용되는 최종 답변 생성 프롬프트
    """
    return (
        "다음은 사용자의 질문 및 MCP 도구 실행 결과입니다.\n\n"
        "사용자 질문:\n" + question + "\n\n"
        "MCP 도구 실행 결과:\n" 
        + json.dumps(executed_results, indent=2, ensure_ascii=False) +
        "\n\n실행 결과를 기반으로 하여 사용자 질문에 대한 답변을 자연스럽게 작성하세요."
    )
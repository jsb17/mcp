import os
import json
import asyncio
from typing import Any, Dict, List

import aiohttp                 # 비동기 HTTP 클라이언트 (Ollama API 호출용)
from dotenv import load_dotenv 
from fastmcp import Client as MCPClient  

load_dotenv()

# Ollama 서버 관련 설정
OLLAMA_URL = os.getenv("OLLAMA_URL") 
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")


# MCP 클라이언트 객체 생성
mcp_client = MCPClient("mcp_server/server_oracle-db.py")


# Utility
def to_ollama_function_description(tool) -> str:
    """
    MCP tools 관련 설명을 텍스트로 변환(prompt에 삽입 목적)
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

def strip_code_block(text: str) -> str:
    """
    ```json ... ``` 또는 ``` ... ``` 감싼 부분 제거
    """
    if text.strip().startswith("```"):
        return "\n".join(line for line in text.strip().splitlines() if not line.strip().startswith("```"))
    return text

async def query_llm(question: str, tool_descriptions: List[str]) -> str:
    """
    LLM 호출을 통해 사용할 적절한 tool들을 선택하고, 이를 순차적으로 실행하여 최종 답변 생성
    """
    async with aiohttp.ClientSession() as session:
        # [1차 요청] MCP 도구들 중 적절한 것을 선택하여 json 형식으로 반환
        system_prompt = (
            "당신은 사용자의 자연어 질문을 해결하기 위해 MCP 도구를 활용하는 시스템입니다.\n"
            "아래는 사용 가능한 도구 목록입니다:\n\n"
            + "\n\n".join(tool_descriptions) +
            "\n\n필요한 도구만 선택하여 다음과 같은 JSON 배열 형식으로 반환하세요:\n"
            '''[
  {"function_name": "get_schema_info", "arguments": {}},
  {"function_name": "generate_sql", "arguments": {"natural_query": "...", "schema_info": "..." }},
  {"function_name": "validate_sql", "arguments": {"sql": "..." }},
  {"function_name": "execute_sql", "arguments": {"exec_sql": "..." }}
]'''
            "\n\n만일, 선택된 도구가 없다면 사전에 학습한 지식을 바탕으로 사용자의 질문에 대해 답변하세요:\n"
        )
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            "stream": False
        }
        async with session.post(f"{OLLAMA_URL}/v1/chat/completions", json=payload) as resp:
            data = await resp.json()
            first_reply = data["choices"][0]["message"]["content"]
            cleaned_first_reply = strip_code_block(first_reply)
            
        # 도구 호출 파약
        try: 
            print('\n📦 LLM 도구 호출 계획:\n', cleaned_first_reply)
            parsed_calls = json.loads(cleaned_first_reply)
        except Exception as e:
            print("\n❌ 선택된 도구 없음 → 답변 그대로 출력\n")
            return cleaned_first_reply.strip()

        # 선택된 도구 파싱 후 순차 실행
        executed_results = []
        memory = {}  # 이전 결과 저장용
        for call in parsed_calls:
            fn_name = call.get("function_name") or parsed_calls.get("function") or parsed_calls.get("name")
            args = call.get("arguments", {})

            if not fn_name:
                continue

            if fn_name == "generate_sql":
                args["natural_query"] =  question
                args["schema_info"] = memory.get("get_schema_info", {})
                # print('[DEBUG] generate_sql args: ', args)

            if fn_name == "validate_sql":
                args["sql"] = memory.get("generate_sql", "")
                # print('[DEBUG] validate_sql args: ', args)

            if fn_name == "execute_sql":
                validation_res = memory.get("validate_sql", "")  # {"valid": True, "message": "SQL 유효함", "sql": sql}
                
                val = validation_res.get("valid")
                msg = validation_res.get("message")
                sql =  validation_res.get("sql")
                
                # TODO 다시 generate_sql 도구를 실행하도록 수정(횟수 제한)
                if val == False:
                    return f"SQL이 유효하지 않습니다: {msg}".strip()
                    
                args["exec_sql"] = str(sql)
                # print('[DEBUG] execute_sql args: ', args)
            
            print(f"🔧 실행 중: {fn_name}({args})")
            call_tool_result = await mcp_client.call_tool(fn_name, args) # 반환값: CallToolResult()
            # CallToolResult()에서 data만 추출 
            if hasattr(call_tool_result, 'data'):
                tool_result = call_tool_result.data
            memory[fn_name] = tool_result
            print(f"✅ {fn_name} 결과: {memory[fn_name]}")

            # 도구 실행 결과 
            executed_results.append({
                "function": fn_name,
                "arguments": args,
                "result": str(memory[fn_name])
            })


        # [2차 요청] 도구 실행 결과를 바탕으로 최종 답변 생성
        system_prompt_2 = (
            "다음은 도구 실행 결과입니다. 이를 종합해 사용자 질문에 대한 답변을 자연스럽게 작성하세요:\n\n"
            + json.dumps(executed_results, indent=2, ensure_ascii=False)
        )
        final_payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt_2},
                {"role": "user", "content": question},
            ],
            "stream": False
        }
        async with session.post(f"{OLLAMA_URL}/v1/chat/completions", json=final_payload) as resp2:
            final_data = await resp2.json()
            return final_data["choices"][0]["message"]["content"]


async def main(): 
    # MCP 클라이언트: 비동기 방식으로 MCP 서버에 연결, 사용 끝날 시 자동 연결 해제 
    async with mcp_client:
        print(f"MCP connected → {mcp_client.is_connected()}")

        tools = await mcp_client.list_tools() # MCP 서버에 연결 -> 서버의 도구 목록 로드 -> LLM이 이해 가능한 형식으로 변환 필요! 
        tool_description = [to_ollama_function_description(tool) for tool in tools]
        
        while True:
            question = input("\n💬 질문을 입력하세요 (exit 입력 시 종료): ")
            if question.strip().lower() == "exit":
                break

            answer = await query_llm(question, tool_description)
            print('\n🤖 LLM 답변:\n', answer)
    
    print(f"MCP connected → {mcp_client.is_connected()}")


if __name__ == "__main__":
    asyncio.run(main())
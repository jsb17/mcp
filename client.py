"""
MultiServerMCP 클라이언트 - 여러 MCP 서버와의 연결을 관리
"""

import os
import json
import asyncio
from typing import Any, Dict, List

import aiohttp                 
from dotenv import load_dotenv 
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools  

from utility.utils import to_ollama_tool_description, strip_code_block


load_dotenv()

# Ollama 서버 관련 설정
OLLAMA_URL = os.getenv("OLLAMA_URL") 
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")

# MCP 서버 설정
MCP_SERVERS_CONFIG = {
    "oracle-db": {
        "command": "python3",
        "args": ["mcp_server/server_oracle-db.py"],
        "transport": "stdio"
    },
    "memory": {
        "command": "python3",
        "args": ["mcp_server/server_memory.py"],
        "transport": "stdio"
    }
}


# MultiServerMCPClient 객체 생성
mcp_client = MultiServerMCPClient(MCP_SERVERS_CONFIG)


# 세션 및 도구 관리 전역 변수 초기화 
server_sessions = {}  # 서버별 세션 저장
all_tools = []        # 모든 서버의 도구 저장
current_session_id = "default"  # 대화 세션 ID: 현재 구현에서는 단순하게 모든 대화가 "default" 세션에 저장되므로, 한 명의 사용자가 하나의 연속된 대화를 나누는 상황에 적합


# 세션 관련 함수 정의
async def initialize_mcp_sessions():
    """
    모든 MCP 서버에 대한 세션을 초기화하고, 각 서버별 도구들을 로드합니다.
    """
    global server_sessions, all_tools
    
    for server_name in MCP_SERVERS_CONFIG.keys():
        try:
            # MCP 서버 세션 초기화
            session = mcp_client.session(server_name) 
            server_sessions[server_name] = session
            
            # 서버 도구 로드
            session_context = await session.__aenter__()  # 서버 START
            tools = await load_mcp_tools(session_context) # [StructuredTool(name='')...] -> LangGraph에서 바로 사용할 수 있는 형식
            all_tools.extend(tools)
            
            print(f"✅ {server_name} 서버 세션 초기화 완료 ({len(tools)}개 도구)\n")
            
        except Exception as e:
            print(f"❌ {server_name} 서버 연결 실패: {str(e)}\n")

async def cleanup_mcp_sessions():
    """
    모든 MCP 서버 세션을 정리합니다.
    """
    global server_sessions
    
    for server_name, session in server_sessions.items():
        try:
            await session.__aexit__(None, None, None) # 서버 EXIT 
            print(f"🔌 {server_name} 세션 종료됨")
        except Exception as e:
            print(f"⚠️ {server_name} 세션 종료 중 오류: {str(e)}")
    
    server_sessions.clear()
    all_tools.clear()


# 대화 이력 저장 관련 함수 정의
async def save_message_to_memory(role: str, content: str, session_id: str = None):
    """
    하나의 메세지를 메모리 서버에 저장합니다.
    """
    if session_id is None:
        session_id = current_session_id
    
    # "save_message" 도구 추출 
    save_msg_tool = None
    for tool in all_tools:
        if tool.name == "save_message":
            save_msg_tool = tool # StructuredTool(name='')
            break
    
    # "save_message" 도구 실행
    if save_msg_tool:
        try:
            result = await save_msg_tool.ainvoke({ # LangChain 또는 LangGraph 에이전트가 MCP 도구를 호출하고 실행하는 과정을 한 번에 처리하는 고수준 래퍼 함수
                "session_id": session_id,
                "role": role,
                "content": content
            })
            print(f"💾 {role} 메시지 저장됨:\n{result}")
        except Exception as e:
            print(f"⚠️ 메시지 저장 실패: {str(e)}")


# 핵심 로직 관련 함수 정의
async def query_llm(question: str, tool_descriptions: List[str]) -> str:
    """
    LLM 호출을 통해 사용할 적절한 tool들을 선택하고, 이를 순차적으로 실행하여 최종 답변을 생성합니다.
    """
    async with aiohttp.ClientSession() as session:
        # [1차 요청] MCP 도구들 중 적절한 것을 선택하여 json 형식으로 반환
        # TODO 테스트 및 수정 필요 
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
            "\n\n메모리 관련 도구 사용법:\n"
            "- 이전 대화를 조회하려면: get_messages\n"
            "- 특정 키워드로 대화를 검색하려면: search_messages + query\n"
            "- 세션 목록을 보려면: list_sessions\n"
            "- session_id는 자동으로 추가되므로 생략 가능합니다.\n\n"
            "만일, 선택된 도구가 없다면 사전에 학습한 지식을 바탕으로 사용자의 질문에 대해 답변하세요:\n"
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
            print(f'\n[DEBUG] LLM 도구 호출 계획:\n{cleaned_first_reply}')
            parsed_calls = json.loads(cleaned_first_reply)
        except Exception as e:
            print("\n[DEBUG] ❌ 선택된 도구 없음 → 답변 그대로 출력\n")
            return cleaned_first_reply.strip()

        # 선택된 도구 파싱 후 순차 실행
        executed_results = []
        memory = {}  # 이전 결과 저장용
        for call in parsed_calls:
            fn_name = call.get("function_name") or parsed_calls.get("function") or parsed_calls.get("name")
            args = call.get("arguments", {})

            if not fn_name:
                continue

            # 메모리 관련 도구들에 session_id 자동 추가
            if fn_name in ["get_messages", "search_messages", "save_message"]:
                if "session_id" not in args:
                    args["session_id"] = current_session_id

            if fn_name == "generate_sql":
                args["natural_query"] =  question
                args["schema_info"] = memory.get("get_schema_info", {})
                # print('[DEBUG] generate_sql args: ', args)

            if fn_name == "validate_sql":
                args["sql"] = memory.get("generate_sql", "")
                # print('[DEBUG] validate_sql args: ', args)

            if fn_name == "execute_sql":
                validation_res = json.loads(memory.get("validate_sql", "")) # langchain_mcp_adapters가 validate_sql()의 결과를 문자열 형태로 반환 => Dict 타입으로 변환 필요 
                
                val = validation_res.get("valid")
                msg = validation_res.get("message")
                sql = validation_res.get("sql")
                
                # SQL이 유효하지 않은 경우 조기 반환
                # TODO 다시 generate_sql 도구를 실행하도록 수정(횟수 제한)
                if val == False:
                    return f"SQL이 유효하지 않습니다: {msg}".strip()
                    
                args["exec_sql"] = str(sql)
                # print('[DEBUG] execute_sql args: ', args)
            
            print(f"\n▶️ 실행 중: {fn_name}({args})")
            
            # 실행할 도구(tool_to_call) 추출 
            global all_tools
            tool_to_call = None
            for tool in all_tools:
                if tool.name == fn_name:
                    tool_to_call = tool
                    break
            
            # 도구(tool_to_call) 실행
            if tool_to_call:
                try:
                    tool_result = await tool_to_call.ainvoke(args)
                    memory[fn_name] = tool_result
                    print(f"🆗 {fn_name} 결과: {memory[fn_name]}")
                except Exception as e:
                    tool_result = f"도구 실행 오류: {str(e)}"
                    memory[fn_name] = tool_result
                    print(f"❌ {fn_name} 실행 실패: {tool_result}")
            else:
                tool_result = f"도구 '{fn_name}'를 찾을 수 없습니다"
                memory[fn_name] = tool_result
                print(f"❌ {tool_result}")

            # 도구 실행 결과를 순차적으로 저장 
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
    # MultiServerMCPClient) 모든 서버와 세션 기반 연결 시도
    try:
        # 모든 서버 세션 초기화 (한 번만 수행)
        await initialize_mcp_sessions()
        
        global all_tools # -> 모든 서버의 도구들이 담겨있음 
        
        # 연결된 서버 및 총 사용 가능한 도구 정보 출력
        print(f"🔌 연결된 서버: {list(MCP_SERVERS_CONFIG.keys())}")
        if all_tools:
            print(f"⚒️  총 사용 가능한 도구({len(all_tools)}개):")
            for tool in all_tools:
                print(f"  - {tool.name}: {getattr(tool, 'description', 'No description')}")
        
        # Ollama LLM에게 전달하기 위한 도구 Description 생성 
        tool_description = [to_ollama_tool_description(tool) for tool in all_tools]
        
        while True:
            question = input("\n💬 질문을 입력하세요 (exit 입력 시 종료): ")
            if question.strip().lower() == "exit":
                break
            # 사용자 메시지 저장
            await save_message_to_memory("user", question)

            answer = await query_llm(question, tool_description)
            print('\n🤖 LLM 답변:\n', answer)
            # 어시스턴트 메시지 저장
            await save_message_to_memory("assistant", answer)

    # MultiServerMCPClient) 서버와 세션 기반 연결 실패 했을 경우
    except Exception as e:
        print(f"❌ MCP 클라이언트 연결 실패: {str(e)}")

    # MultiServerMCPClient) 연결된 모든 세션 정리
    finally:
        await cleanup_mcp_sessions()


if __name__ == "__main__":
    asyncio.run(main())
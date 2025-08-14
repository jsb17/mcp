"""
plan_tools 노드 - MCP 도구 선택/계획 노드
"""

import os
import sys
import json

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(BASE_DIR)
from utils.utils import generate_tool_descriptions_for_ollama, strip_code_block, get_plan_tools_node_prompt

# 상위 디렉토리를 Python 경로에 추가
sys.path.append(os.path.dirname(os.path.join(os.path.dirname(__file__), '..')))
from state import AgentState

async def plan_tools_node(state: AgentState, config, mcp_wrapper) -> AgentState:
        """도구 계획 노드"""
        print(f"🎯 [plan_tools_node] 시작")
        question = state["question"]

        all_tools = mcp_wrapper.all_tools
        
        # 도구 설명 생성
        tool_descriptions = [generate_tool_descriptions_for_ollama(tool) for tool in all_tools]
        
        # LLM에게 도구 선택 요청
        system_prompt = get_plan_tools_node_prompt(tool_descriptions)
        
        print(f"🎯 [plan_tools_node] Ollama 호출 (HTTP)중... ({config.ollama_url}, {config.ollama_model})")
        import aiohttp
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": config.ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question}
                ],
                "stream": False
            }
            async with session.post(f"{config.ollama_url}/v1/chat/completions", json=payload) as resp:
                print(f"🎯 [plan_tools_node] HTTP 응답 받음: {resp.status}")
                data = await resp.json()
                llm_response = data["choices"][0]["message"]["content"]
                cleaned_response = strip_code_block(llm_response)
                
        # 도구 호출 파악 및 파싱
        try: 
            print(f'🎯 [plan_tools_node] LLM 도구 호출 계획:\n{cleaned_response}')
            parsed_calls = json.loads(cleaned_response)
            state["tool_calls"] = parsed_calls if isinstance(parsed_calls, list) else [parsed_calls]
        # 호출된 도구가 없다면, 1차 LLM 답변을 최종 답변으로 제공 
        except Exception as e: 
            print(f"🎯 [plan_tools_node] ❌ JSON 파싱 실패: {e}\n원본 응답을 최종 답변으로 사용")
            # JSON 파싱 실패시 원본 응답을 최종 답변으로 설정
            state["tool_calls"] = []
            state["final_answer"] = cleaned_response

        print(f"🎯 [plan_tools_node] 완료")
        return state
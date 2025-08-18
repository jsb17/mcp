"""
plan_tools 노드 - MCP 도구 선택/계획 노드
"""

import os
import sys
import json
import aiohttp

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils.utils import generate_tool_descriptions_for_ollama, strip_code_block, strip_think_block, get_plan_tools_node_prompt
from state import AgentState


async def plan_tools_node(state: AgentState, config, mcp_wrapper) -> AgentState:
        """도구 계획 노드"""
        print(f"\n🎯 [plan_tools_node] 시작")

        question = state["question"]        # 사용자 질문
        all_tools = mcp_wrapper.all_tools   # MCP 도구
        
        # 도구 설명 생성
        tool_descriptions = [generate_tool_descriptions_for_ollama(tool) for tool in all_tools]

        # 시스템 프롬프트 생성
        system_prompt = get_plan_tools_node_prompt(tool_descriptions)
        
        print(f"🎯 [plan_tools_node] Ollama 호출(HTTP) 중... ({config.ollama_url}, {config.ollama_model})")
        print(f"🎯 [plan_tools_node] sys prompt:\n{system_prompt}")
        
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": config.ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question}
                ],
                "options": {
                    "temperature": 0,     # 무작위성 제거
                    "top_p": 1,           # 확률 컷오프 제거
                    "repeat_penalty": 1   # 반복 억제 영향 최소화
                },
                "stream": False
            }
            async with session.post(f"{config.ollama_url}/v1/chat/completions", json=payload) as resp:
                data = await resp.json()
                llm_response = data["choices"][0]["message"]["content"]
                print(f"\n🎯 [plan_tools_node] 원본 LLM 응답:\n'{llm_response}'")
                cleaned_response = strip_code_block(llm_response)
                cleaned_response = strip_think_block(cleaned_response) # qwen 모델 특화
                   
        # 도구 호출 파악 및 파싱
        try: 
            print(f'🎯 [plan_tools_node] (최종) LLM 도구 호출 계획:\n{cleaned_response}')
            
            parsed_calls = json.loads(cleaned_response)
            state["tool_calls"] = parsed_calls if isinstance(parsed_calls, list) else [parsed_calls]
        
        # 호출된 도구가 없다면, 1차 LLM 답변을 최종 답변으로 제공 
        except Exception as e: 
            print(f"🎯 [plan_tools_node] ❌ JSON 파싱 실패: {e} 원본 응답을 최종 답변으로 사용")
            # JSON 파싱 실패시 원본 응답을 최종 답변으로 설정
            state["tool_calls"] = []
            state["final_answer"] = cleaned_response

        print(f"🎯 [plan_tools_node] 완료")
        return state
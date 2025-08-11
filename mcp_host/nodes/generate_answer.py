"""
generate_answer 노드 - MCP 도구 실행 결과 기반 최종 답변 생성 노드
"""

import os
import sys
import json
import aiohttp

# 상위 디렉토리를 Python 경로에 추가
sys.path.append(os.path.dirname(os.path.join(os.path.dirname(__file__), '..')))
from state import AgentState

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(BASE_DIR)
from utils.utils import get_generate_answer_node_prompt


async def generate_answer_node(state: AgentState, config) -> AgentState:
        """최종 답변 생성 노드"""
        print(f"🤖 [generate_answer_node] 시작")
        question = state["question"]
        executed_results = state.get("executed_results", [])
        # state["dataframe"] = pd.DataFrame(executed_results)
        
        if not executed_results:
            print(f"🤖 [generate_answer_node] 도구 실행 결과 없음")
            state["final_answer"] = "도구를 사용할 수 없어 답변을 생성할 수 없습니다."
            return state
        
        # 최종 답변 생성
        system_prompt = get_generate_answer_node_prompt(executed_results)
        
        
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
                data = await resp.json()
                final_answer = data["choices"][0]["message"]["content"]
                print('\n🤖 LLM 답변:\n', final_answer)
        
        state["final_answer"] = final_answer
        print(f"🤖 [generate_answer_node] 완료")
        return state
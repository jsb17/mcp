"""
generate_answer 노드 - MCP 도구 실행 결과 기반 최종 답변 생성 노드
"""

import os
import sys
import json
import aiohttp
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from state import AgentState
from utils.utils import get_generate_answer_node_prompt, strip_think_block


async def generate_answer_node(state: AgentState, config) -> AgentState:
        """최종 답변 생성 노드"""
        print(f"\n🤖 [generate_answer_node] 시작")
        question = state["question"]
        executed_results = state.get("executed_results", [])
        
        if not executed_results:
            print(f"🤖 [generate_answer_node] 도구 실행 결과 없음")
            state["final_answer"] = "도구를 사용할 수 없어 답변을 생성할 수 없습니다."
            return state
       
        # "execute_sql"이 포함된 아이템 찾기
        execute_sql_item = next(
            (item for item in executed_results if item.get("function") == "execute_sql"),
            None
        )

        if execute_sql_item:
            # execute_sql 처리
            executed_results_json = json.loads(execute_sql_item["result"])
            state["dataframe"] = pd.DataFrame(executed_results_json)
            system_prompt = (
                "다음은 사용자의 질문에 대한 Text to SQL 실행 결과입니다."
                "실행 결과를 분석하여 사용자에게 간단한 분석 보고서를 제공하세요\n\n"
                + json.dumps(executed_results_json, indent=2, ensure_ascii=False)
            )
        else:
            # execute_sql이 전혀 없을 때
            system_prompt = get_generate_answer_node_prompt(question, executed_results)
        
        print(f'🤖 [generate_answer_node] 최종 답변 SYS prompt: {system_prompt}')

        # 최종 답변 생성
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": config.ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt}
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
                final_answer = data["choices"][0]["message"]["content"]
                # print('🤖 [generate_answer_node] 최종 LLM 답변:\n', final_answer)
                final_answer = strip_think_block(final_answer) # qwen 모델 특화
        
        state["final_answer"] = final_answer
        print(f"🤖 [generate_answer_node] 답변 생성 완료")
        return state
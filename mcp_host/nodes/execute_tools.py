"""
execute_tools 노드 - MCP 도구 순차 실행 노드
"""

import os
import sys
import json
from typing import Any, Dict

# 상위 디렉토리를 Python 경로에 추가
sys.path.append(os.path.dirname(os.path.join(os.path.dirname(__file__), '..')))
from state import AgentState


async def _execute_tool(fn_name: str, args: Dict, mcp_wrapper) -> Any:
        """도구 실행 - 스레드 안전한 래퍼 사용"""
        print(f"\n▶️ 실행 중: {fn_name}({args})")
        
        result = await mcp_wrapper.execute_tool(fn_name, args)
        print(f"▶️ [_execute_tool] {fn_name} 완료: {str(result)[:100]}...")
        return result

async def execute_tools_node(state: AgentState, mcp_wrapper) -> AgentState:
        """도구 실행 노드"""
        print(f"⚙️ [execute_tools_node] 시작")
        tool_calls = state.get("tool_calls", [])
        print(f"⚙️ [execute_tools_node] 실행할 도구: {len(tool_calls)}개")
        executed_results = []
        memory = {}
        
        for call in tool_calls:
            fn_name = call.get("function_name") or call.get("function") or call.get("name")
            args = call.get("arguments", {})
            
            if not fn_name:
                continue
                
            # 메모리 관련 도구에 session_id 자동 추가
            if fn_name in ["get_messages", "search_messages", "save_message"]:
                if "session_id" not in args:
                    args["session_id"] = state["session_id"]
            
            # SQL 관련 도구 체이닝
            if fn_name == "generate_sql":
                args["natural_query"] = state["question"]
                args["schema_info"] = memory.get("get_schema_info", {})
            elif fn_name == "validate_sql":
                args["sql"] = memory.get("generate_sql", "")
            elif fn_name == "execute_sql":
                validation_res = json.loads(memory.get("validate_sql", "{}"))
                if not validation_res.get("valid", False):
                    executed_results.append({
                        "function": fn_name,
                        "arguments": args,
                        "result": f"SQL이 유효하지 않습니다: {validation_res.get('message', '')}"
                    })
                    continue
                args["exec_sql"] = str(validation_res.get("sql", ""))
            
            # 도구 실행
            tool_result = await _execute_tool(fn_name, args, mcp_wrapper)
            memory[fn_name] = tool_result
            print(f"🆗 {fn_name} 결과: {memory[fn_name]}")
            
            executed_results.append({
                "function": fn_name,
                "arguments": args,
                "result": str(tool_result)
            })
        
        state["executed_results"] = executed_results
        print(f"⚙️ [execute_tools_node] 완료 - {len(executed_results)}개 결과")
        return state
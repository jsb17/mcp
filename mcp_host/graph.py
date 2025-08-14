"""
LangGraph 기반 에이전트 시스템 - MCP 서버와 연동
"""

import os
import sys

from dotenv import load_dotenv
from langgraph.graph import StateGraph, END

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from nodes.generate_answer import generate_answer_node
from nodes.plan_tools import plan_tools_node
from nodes.execute_tools import execute_tools_node
from state import AgentState
from config import AgentConfig
from mcp_wrapper import ThreadSafeMCPWrapper


load_dotenv()


class MCPAgent:
    """
    MCP 서버와 연동된 LangGraph 에이전트
    """
    def __init__(self, config: AgentConfig):
        self.config = config
        self.mcp_wrapper = ThreadSafeMCPWrapper(config.mcp_servers_config)
        self.graph = None
        
    async def initialize(self):
        """MCP 세션 초기화 및 그래프 구성"""
        await self.mcp_wrapper.initialize()
        self._build_graph()
        
    @property
    def all_tools(self):
        """모든 도구 목록 반환"""
        return self.mcp_wrapper.all_tools
    
    def _build_graph(self):
        """LangGraph 워크플로우 구성"""
        workflow = StateGraph(AgentState)
        
        # 노드 추가
        async def _plan_tools_wrapper(state):
            return await plan_tools_node(state, self.config, self.mcp_wrapper)
        async def _execute_tools_wrapper(state):
            return await execute_tools_node(state, self.mcp_wrapper)
        async def _generate_answer_wrapper(state):
            return await generate_answer_node(state, self.config)
        
        workflow.add_node("plan_tools", _plan_tools_wrapper)
        workflow.add_node("execute_tools", _execute_tools_wrapper)
        workflow.add_node("generate_answer", _generate_answer_wrapper) # lambda state: generate_answer_node(state, self.config)
        
        # 엣지 정의 - 조건부 라우팅
        workflow.set_entry_point("plan_tools")
        
        # plan_tools에서 조건부 분기
        def should_execute_tools(state):

            # 도구 호출이 1개 이상이면 execute_tools로
            if state.get("tool_calls") and len(state["tool_calls"]) > 0:
                return "execute_tools"
            # 도구 호출이 없으면 바로 종료 
            else:
                return END
        
        workflow.add_conditional_edges(
            "plan_tools",
            should_execute_tools,
            {
                "execute_tools": "execute_tools",
                END: END
            }
        )
        
        workflow.add_edge("execute_tools", "generate_answer")
        workflow.add_edge("generate_answer", END)
        
        self.graph = workflow.compile()
    
    async def run_query(self, question: str, session_id: str = None) -> str:
        """질문 -> 그래프 실행"""
        if session_id is None:
            session_id = self.config.session_id
            
        await self._save_message("user", question, session_id)
        print(f"📝 [run_query] 사용자 메시지 저장")
        
        # 초기 상태 설정
        initial_state = {
            "messages": [],
            "question": question,
            "tool_calls": None,
            "executed_results": [],
            "final_answer": "",
            "session_id": session_id,
        }
        
        # 그래프 실행
        final_state = await self.graph.ainvoke(initial_state)
        answer = final_state["final_answer"]

        await self._save_message("assistant", answer, session_id)
        print(f"💾 [run_query] 어시스턴트 메시지 저장")
        
        # DataFrame이 존재하면 answer와 함께 반환
        if final_state.get("dataframe") is not None:
            return {"answer": answer, "dataframe": final_state["dataframe"]}
        else:
            return {"answer": answer}
    
    async def _save_message(self, role: str, content: str, session_id: str):
        """메시지 저장"""
        try:
            result = await self.mcp_wrapper.execute_tool(
                "save_message",
                {
                    "session_id": session_id,
                    "role": role,
                    "content": content
                }
            )
            print(f"💾 [_save_message] 완료: {str(result)[:100]}...")
        except Exception as e:
            print(f"💾 [_save_message] 실패: {str(e)}")
            import traceback
            traceback.print_exc()
    
    async def cleanup(self):
        """MCP 서버 세션 정리"""
        self.mcp_wrapper.cleanup()
        print(f"🧹 [cleanup] 정리 완료")
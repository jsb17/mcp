"""
LangGraph 기반 에이전트 시스템 - MCP 서버와 연동
"""

import os
import json
import pandas as pd
import asyncio
import logging
import threading
import concurrent.futures
from typing import Any, Dict, List, TypedDict, Optional
from dataclasses import dataclass

import aiohttp
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from utility.utils import to_ollama_tool_description, strip_code_block, get_tool_planning_prompt


# 로그 레벨 및 포맷 설정
logging.basicConfig(level=logging.INFO, format="🔧 [%(levelname)s] %(message)s")


load_dotenv()
# CONFIG_FILE_PATH="mcp_config.json"

@dataclass
class AgentConfig:
    """에이전트 설정"""
    session_id: str = "default"
    ollama_url: str = os.getenv("OLLAMA_URL")
    ollama_model: str = os.getenv("OLLAMA_MODEL")
    mcp_servers_config = None

    
    def __post_init__(self):
        if self.mcp_servers_config is None:
            self.mcp_servers_config = {
    "oracle-db": {
        "command": "python3",
        "args": [
            "mcp_server/server_oracle-db.py"
        ],
        "transport": "stdio"
    },
    "memory": {
        "command": "python3",
        "args": [
            "mcp_server/server_memory.py"
        ],
        "transport": "stdio"
    }
}


class AgentState(TypedDict):
    """에이전트 상태"""
    messages: List[HumanMessage | AIMessage]
    question: str
    tool_calls: Optional[List[Dict]] # MCP 서버로부터 호출된 도구들 
    executed_results: List[Dict]
    final_answer: str
    session_id: str
    # skip_tools: bool  # JSON 파싱 실패시 도구 실행 건너뛰기 플래그

# 문제 상황: Streamlit에서 MCP 도구 정상 실행 X (호출은 되나, 결과값 반환이 안 되고 무한 루프)
# 문제 원인: Streamlit의 이벤트 루프와 MCP 세션의 asyncio 컨텍스트 충돌
#           더 구체적으로는, Streamlit은 loop.run_until_complete()로 실행되는데, MCP 세션도 같은 루프를 사용하면서 데드락 발생
# 문제 해결: ThreadSafeMCPWrapper
#           별도 스레드에서 MCP 세션 관리: 완전히 독립된 이벤트 루프 사용(run_in_executor) => 충돌 방지 및 서버 한 번만 시작함으로써 성능 효율성 보장 
#  🔧 동작 방식:
#   Main Thread (Streamlit)    →    Worker Thread (MCP)
#         ↓                              ↓
#      Streamlit 이벤트 루프      →    독립 이벤트 루프
#         ↓                              ↓
#      MCPAgent.execute_tool     →    MCP 서버들과 통신
#         ↓                              ↓
#      결과 반환                ←      도구 실행 결과
class ThreadSafeMCPWrapper:
    """스레드 안전한 MCP 클라이언트 래퍼"""
    
    def __init__(self, mcp_config):
        self.mcp_config = mcp_config
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.loop = None
        self.mcp_client = None
        self.server_sessions = {}
        self.all_tools = []
        self._initialized = False
        
    async def initialize(self):
        """별도 스레드에서 MCP 초기화""" # 각 mcp 서버들은 별도의 스레드에서 시작 및 세션 초기화 됨 
        if self._initialized:
            print("🔗 [ThreadSafeMCPWrapper] 이미 초기화됨")
            return
            
        print("🔗 [ThreadSafeMCPWrapper] 별도 스레드에서 MCP 초기화 시작...")
        
        def _init_in_thread():
            # 새로운 이벤트 루프 생성
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            async def _async_init():
                self.mcp_client = MultiServerMCPClient(self.mcp_config)
                
                for server_name in self.mcp_config.keys():
                    try:
                        print(f"🔗 [ThreadSafeMCPWrapper] {server_name} 서버 연결 중...")
                        session = self.mcp_client.session(server_name)
                        session_context = await session.__aenter__() # 서버 시작
                        self.server_sessions[server_name] = session
                        
                        # 각 서버 별로 존재하는 모든 도구들 load & all_tools에 저장 
                        tools = await load_mcp_tools(session_context) 
                        self.all_tools.extend(tools)
                        
                        print(f"✅ {server_name} 초기화 완료 ({len(tools)}개 도구)")
                        for tool in tools:
                            print(f"  - {tool.name}")
                    except Exception as e:
                        print(f"❌ {server_name} 초기화 실패: {e}")
                
                print(f"🔗 [ThreadSafeMCPWrapper] 총 {len(self.all_tools)}개 도구 로드 완료")
                self._initialized = True
                
            # 스레드 내에서 asyncio 실행
            self.loop.run_until_complete(_async_init())
            
        # 별도 스레드에서 실행 (streamlit과 MCP 서버 세션 간 충돌 막기 위해)
        await asyncio.get_event_loop().run_in_executor(self.executor, _init_in_thread)
        
    async def execute_tool(self, tool_name: str, args: Dict) -> Any:
        """도구 실행"""
        if not self._initialized:
            return "MCP 클라이언트가 초기화되지 않았습니다"
            
        def _execute_in_thread():
            # 스레드 내에서 도구 실행
            async def _async_execute():
                tool_to_call = None
                for tool in self.all_tools:
                    if tool.name == tool_name:
                        tool_to_call = tool
                        break
                
                if tool_to_call:
                    try:
                        return await asyncio.wait_for(
                            tool_to_call.ainvoke(args),
                            timeout=10.0
                        )
                    except asyncio.TimeoutError:
                        return f"도구 실행 타임아웃: {tool_name}"
                    except Exception as e:
                        return f"도구 실행 오류: {str(e)}"
                else:
                    return f"도구 '{tool_name}'를 찾을 수 없습니다"
            
            # 기존 루프에서 실행
            return self.loop.run_until_complete(_async_execute())
        
        # 별도 스레드에서 도구 실행
        return await asyncio.get_event_loop().run_in_executor(
            self.executor, _execute_in_thread
        )
        
    def cleanup(self):
        """정리"""
        if self.loop and not self.loop.is_closed():
            def _cleanup_in_thread():
                async def _async_cleanup():
                    for server_name, session in self.server_sessions.items():
                        try:
                            await session.__aexit__(None, None, None)
                        except Exception as e:
                            print(f"세션 정리 오류: {e}")
                    self.server_sessions.clear()
                    self.all_tools.clear()
                
                self.loop.run_until_complete(_async_cleanup())
                self.loop.close()
                
            self.executor.submit(_cleanup_in_thread)
        
        self.executor.shutdown(wait=True)

class MCPAgent:
    """MCP 서버와 연동하는 LangGraph 에이전트"""
    
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
        workflow.add_node("plan_tools", self.plan_tools_node)
        workflow.add_node("execute_tools", self.execute_tools_node)
        workflow.add_node("generate_answer", self.generate_answer_node)
        
        # 엣지 정의 - 조건부 라우팅
        workflow.set_entry_point("plan_tools")
        
        # plan_tools에서 조건부 분기
        def should_execute_tools(state):
            # skip_tools 플래그가 True면 바로 종료
            # if state.get("skip_tools", False):
            #     return END
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
                "generate_answer": "generate_answer", 
                END: END
            }
        )
        
        workflow.add_edge("execute_tools", "generate_answer")
        workflow.add_edge("generate_answer", END)
        
        self.graph = workflow.compile()
    
    async def plan_tools_node(self, state: AgentState) -> AgentState:
        """도구 계획 노드"""
        print(f"🎯 [plan_tools_node] 시작")
        question = state["question"]
        
        # 도구 설명 생성
        print(f"🎯 [plan_tools_node] 도구 설명 생성 중... ({len(self.all_tools)}개 도구)")
        tool_descriptions = [to_ollama_tool_description(tool) for tool in self.all_tools]
        
        # LLM에게 도구 선택 요청
        print(f"🎯 [plan_tools_node] 도구 계획 프롬프트 생성 중...")
        system_prompt = get_tool_planning_prompt(tool_descriptions)
        
        print(f"🎯 [plan_tools_node] Ollama 호출 중... ({self.config.ollama_url}, {self.config.ollama_model})")
        import aiohttp
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": self.config.ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question}
                ],
                "stream": False
            }
            print(f"🎯 [plan_tools_node] HTTP 요청 전송 중...")
            async with session.post(f"{self.config.ollama_url}/v1/chat/completions", json=payload) as resp:
                print(f"🎯 [plan_tools_node] HTTP 응답 받음: {resp.status}")
                data = await resp.json()
                llm_response = data["choices"][0]["message"]["content"]
                cleaned_response = strip_code_block(llm_response)
                print(f"🎯 [plan_tools_node] LLM 응답: {cleaned_response[:100]}...")
                
        
        # 도구 호출 파악 및 파싱
        try: # 호출된 도구가 있다면 파싱
            print(f'🎯 [plan_tools_node] LLM 도구 호출 계획:\n{cleaned_response}')
            parsed_calls = json.loads(cleaned_response)
            state["tool_calls"] = parsed_calls if isinstance(parsed_calls, list) else [parsed_calls]
            print(f"🎯 [plan_tools_node] 파싱된 도구 호출: {len(state['tool_calls'])}개")
        except Exception as e: # 호출된 도구가 없다면, 1차 LLM 답변을 최종 답변으로 제공 
            print(f"🎯 [plan_tools_node] ❌ JSON 파싱 실패: {e}")
            print(f"🎯 [plan_tools_node] 원본 응답을 최종 답변으로 사용")
            # JSON 파싱 실패시 원본 응답을 최종 답변으로 설정
            state["tool_calls"] = []
            state["final_answer"] = cleaned_response
            # state["skip_tools"] = True  # 도구 실행과 답변 생성을 건너뛰도록 플래그 설정
        
        print(f"🎯 [plan_tools_node] 완료")
        return state
    
    async def execute_tools_node(self, state: AgentState) -> AgentState:
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
            tool_result = await self._execute_tool(fn_name, args)
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
    
    async def generate_answer_node(self, state: AgentState) -> AgentState:
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
        system_prompt = (
            "다음은 도구 실행 결과입니다. 이를 종합해 사용자 질문에 대한 답변을 자연스럽게 작성하세요:\n\n"
            # + pd.DataFrame(executed_results) 
            # "단, 답변에 SQL 실행 결과는 포함하지 마시오.\n"
            + json.dumps(executed_results, indent=2, ensure_ascii=False) # python dict -> str
        )
        
        
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": self.config.ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question}
                ],
                "stream": False
            }
            async with session.post(f"{self.config.ollama_url}/v1/chat/completions", json=payload) as resp:
                data = await resp.json()
                final_answer = data["choices"][0]["message"]["content"]
                print('\n🤖 LLM 답변:\n', final_answer)
        
        state["final_answer"] = final_answer
        print(f"🤖 [generate_answer_node] 완료")
        return state
    
    async def _execute_tool(self, fn_name: str, args: Dict) -> Any:
        """도구 실행 - 스레드 안전한 래퍼 사용"""
        print(f"\n▶️ 실행 중: {fn_name}({args})")
        print(f"▶️ [_execute_tool] {fn_name} 스레드 안전 실행 중...")
        
        result = await self.mcp_wrapper.execute_tool(fn_name, args)
        print(f"▶️ [_execute_tool] {fn_name} 완료: {str(result)[:100]}...")
        return result
    
#     def get_tool_planning_prompt(self, tool_descriptions: List[str]) -> str:
#         """도구 계획 프롬프트"""
#         return (
#             "당신은 사용자의 자연어 질문을 해결하기 위해 MCP 도구를 활용하는 시스템입니다.\n"
#             "아래는 사용 가능한 도구 목록입니다:\n\n"
#             + "\n\n".join(tool_descriptions) +
#             "\n\n필요한 도구만 선택하여 다음과 같은 JSON 배열 형식으로 반환하세요:\n"
#             '''[
#   {"function_name": "get_schema_info", "arguments": {}},
#   {"function_name": "generate_sql", "arguments": {"natural_query": "...", "schema_info": "..." }},
#   {"function_name": "validate_sql", "arguments": {"sql": "..." }},
#   {"function_name": "execute_sql", "arguments": {"exec_sql": "..." }}
# ]'''
#             "\n\n메모리 관련 도구 사용법:\n"
#             "- 이전 대화를 조회하려면: get_messages\n"
#             "- 특정 키워드로 대화를 검색하려면: search_messages + query\n"
#             "- session_id는 자동으로 추가되므로 생략 가능합니다.\n\n"
#             "만일, 선택된 도구가 없다면 빈 배열 []을 반환하세요."
#         )
    
    async def run_query(self, question: str, session_id: str = None) -> str:
        """질문 실행"""
        print(f"🚀 [run_query] 질문 시작: {question}")
        if session_id is None:
            session_id = self.config.session_id
            
        print(f"📝 [run_query] 사용자 메시지 저장")
        await self._save_message("user", question, session_id)
        
        # 초기 상태 설정
        initial_state = {
            "messages": [],
            "question": question,
            "tool_calls": None,
            "executed_results": [],
            # "dataframe": pd.DataFrame(),
            "final_answer": "",
            "session_id": session_id,
            # "skip_tools": False
        }
        
        print(f"⚙️ [run_query] 그래프 실행 중...")
        # 그래프 실행
        final_state = await self.graph.ainvoke(initial_state)
        answer = final_state["final_answer"]
        
        print(f"💾 [run_query] 어시스턴트 메시지 저장")
        await self._save_message("assistant", answer, session_id)
        
        print(f"✅ [run_query] 완료: {answer}")
        return answer
    
    async def _save_message(self, role: str, content: str, session_id: str):
        """메시지 저장 - 스레드 안전한 래퍼 사용"""
        print(f"💾 [_save_message] 시작 - role: {role}, session: {session_id}")
        
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
        """세션 정리"""
        print(f"🧹 [cleanup] 세션 정리 시작...")
        self.mcp_wrapper.cleanup()
        print(f"🧹 [cleanup] 정리 완료")
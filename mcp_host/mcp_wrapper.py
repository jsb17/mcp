"""
MCP Client 래퍼 - 별도의 Thread에서 MCP 세션을 독립적으로 관리하기 위함

 🔧 동작 방식: 완전히 독립된 이벤트 루프 사용(run_in_executor) 
  Main Thread (Streamlit)    →    Worker Thread (MCP)
        ↓                              ↓
     Streamlit 이벤트 루프     →    독립 이벤트 루프
        ↓                              ↓
     MCPAgent.execute_tool   →    MCP 서버들과 통신
        ↓                              ↓
     결과 반환                ←      도구 실행 결과

  => 충돌 방지 및 서버 한 번만 시작함으로써 성능 효율성 보장 
"""

import os
import asyncio
import concurrent.futures
from typing import Any, Dict

from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_mcp_adapters.client import MultiServerMCPClient


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class ThreadSafeMCPWrapper:
    def __init__(self, mcp_servers_config):
        self.mcp_servers_config = mcp_servers_config
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.loop = None
        self.mcp_client = None
        self.server_sessions = {}
        self.all_tools = []
        self._initialized = False
        
    async def initialize(self):
        """
        별도 Thread에서 MCP 서버 시작 및 세션 초기화
        """ 
        if self._initialized:
            print("🔗 [ThreadSafeMCPWrapper] MCP 서버 세션이 이미 초기화 되었습니다.")
            return
            
        def _init_in_thread():
            # 새로운 이벤트 루프 생성
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            async def _async_init():
                original_cwd = os.getcwd()
                try:
                    # MCP 서버 실행 시에만 임시로 디렉토리 변경
                    os.chdir(BASE_DIR) 

                    # MultiServerMCPClient 객체 생성 
                    self.mcp_client = MultiServerMCPClient(self.mcp_servers_config)
                    
                    # MCP 서버 시작 및 세션 초기화
                    for server_name in self.mcp_servers_config.keys():
                        try:
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
                
                finally:
                    os.chdir(original_cwd)  # 디렉터리 원복

            # 스레드 내에서 asyncio 실행,  루프를 직접 실행(run_until_complete)
            self.loop.run_until_complete(_async_init())
            
        # 별도 스레드에서 실행 (streamlit과 MCP 서버 세션 간 충돌 막기 위해)
        await asyncio.get_event_loop().run_in_executor(self.executor, _init_in_thread)
        

    async def execute_tool(self, tool_name: str, args: Dict) -> Any:
        """
        MCP 도구 실행
        """
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
        """
        MCP 서버 세션 정리
        """
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
"""
Streamlit 웹 UI - LangGraph 에이전트 인터페이스
"""

import os 
import time
import asyncio

import streamlit as st
from dotenv import load_dotenv

from graph import MCPAgent
from config import AgentConfig


load_dotenv() 


# 페이지 설정
st.set_page_config(
    page_title="MCP Agent Chat",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 사이드바 설정
with st.sidebar:
    st.title("⚙️ 설정")
    
    # 대화 세션 ID 설정 
    session_id = st.text_input(
        "세션 ID", 
        value=st.session_state.get('session_id', 'default'),
        help="대화 세션을 구분하는 ID입니다"
    )
    
    # Ollama 설정
    ollama_url = st.text_input(
        "Ollama URL", 
        value=os.getenv("OLLAMA_URL")
    )

    # Ollama 모델 목록
    model_options = [
        "gpt-oss:20b",
        "gpt-oss:120b",
        "gemma3:12b", 
        "gemma3:27b",
        "qwen3:14b",
        "qwen3:30b",
        "qwen3:32b", 
        "mistral:latest",
        "llama3.1:8b"
    ]
    ollama_model = st.selectbox(
        "Ollama 모델", 
        model_options,
        index=3
    )
    
    # MCP 서버 연결 상태 표시
    if 'agent_initialized' in st.session_state and st.session_state.agent_initialized:
        st.success("✅ MCP 서버 연결됨")
        if 'agent_tools' in st.session_state:
            with st.expander("🛠️ 사용 가능한 도구들"):
                for tool_name in st.session_state.agent_tools:
                    st.code(tool_name)
    else:
        st.warning("⚠️ MCP 서버 연결 필요")
    
    # MCP 서버 연결 버튼
    if st.button("🔄 MCP 서버 연결"):
        with st.spinner("MCP 서버 연결 중..."):
            try:
                # 에이전트 설정 
                config = AgentConfig(
                    session_id=session_id,
                    ollama_url=ollama_url,
                    ollama_model=ollama_model
                )
                
                # 에이전트 초기화
                agent = MCPAgent(config)
                
                # 기존 이벤트 루프 확인 및 사용
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_closed():
                        raise RuntimeError("Loop is closed")
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                loop.run_until_complete(agent.initialize())
                
                # 세션 상태 저장
                st.session_state.agent = agent
                st.session_state.agent_initialized = True
                st.session_state.agent_tools = [tool.name for tool in agent.all_tools]
                st.session_state.session_id = session_id
                
                st.rerun()
                
            except Exception as e:
                st.error(f"🚫 MCP 서버 연결 실패: {str(e)}")
    
    # MCP 서버 종료 버튼
    if st.button("🧹 MCP 서버 종료"):
        if 'agent' in st.session_state:
            try:
                # 기존 이벤트 루프 확인 및 사용 (새 루프 생성 X)
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_closed():
                        raise RuntimeError("Loop is closed")
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                loop.run_until_complete(st.session_state.agent.cleanup())
                
                # 세션 상태 정리
                for key in ['agent', 'agent_initialized', 'agent_tools']:
                    if key in st.session_state:
                        del st.session_state[key]
                
                st.rerun()
                
            except Exception as e:
                st.error(f"🚫 MCP 서버 종료 실패: {str(e)}")

# 메인 화면
st.title("🤖 MCP Agent Chat")
st.markdown("Oracle DB와 메모리 관리가 가능한 AI 어시스턴트입니다.")

# 채팅 히스토리 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# 채팅 히스토리 표시
for message in st.session_state.messages:
    if message["role"] == "dataframe":
        st.dataframe(message["content"])
    else:
        st.chat_message(message["role"]).markdown(message["content"])

# 사용자 입력
if prompt := st.chat_input("🗨️ 질문을 입력하세요."):
    # MCP 서버 연결 확인
    if 'agent_initialized' not in st.session_state or not st.session_state.agent_initialized:
        st.error("⚠️ 먼저 사이드 바에서 MCP 서버를 연결 해주세요.")
        st.stop()
    
    # 사용자 메시지(질문) 추가
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 어시스턴트 응답 추가
    with st.chat_message("assistant"):
        with st.spinner("답변 생성 중..."):
            try:
                start_time = time.time()
                
                # 기존 이벤트 루프 확인 및 사용
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_closed():
                        raise RuntimeError("Loop is closed")
                # 필요할 때만 새 루프 생성 
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                print(f"\n\n\n🙍 [user question] {prompt}")
                response = loop.run_until_complete(
                    st.session_state.agent.run_query(prompt, st.session_state.session_id)
                )
                
                end_time = time.time()
                total_time = end_time - start_time
                
                print(f"\n\n[DEBUG] 총 답변 생성 시간: {total_time:.2f}초")
                print(f"[DEBUG] 최종 LLM 답변: {response}")

                # SQL 실행 결과를 데이터프레임 형태로 출력
                if response.get("dataframe") is not None and not response.get("dataframe").empty:
                    st.dataframe(response.get("dataframe"))
                    st.session_state.messages.append({"role": "dataframe", "content": response.get("dataframe")})
                # 어시스턴트 메시지 추가
                st.markdown(response.get("answer"))
                st.session_state.messages.append({"role": "assistant", "content": response.get("answer")})
                
            except Exception as e:
                error_message = f"🚫 오류가 발생했습니다: {str(e)}"
                import traceback
                traceback.print_exc()
                st.error(error_message)
                st.session_state.messages.append({"role": "assistant", "content": error_message})

# 하단 정보
st.markdown("---")
st.caption("💡 팁: Oracle DB 접근 및 조회, 이전 대화 내역 조회 등의 기능을 사용할 수 있습니다.")
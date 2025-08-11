"""
Streamlit 웹 UI - LangGraph 에이전트 인터페이스
"""

import os 
import re
import json
import asyncio
import pandas as pd

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
    # 모델 목록
    model_options = [
        "gpt-oss:20b",
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
        index=2
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
    
    # MCP 서버 연결/서버 세션 초기화 버튼
    if st.button("🔄 MCP 서버 연결"):
        with st.spinner("MCP 서버 연결 중..."):
            try:
                print(f"[DEBUG] MCP 서버 연결 시작...")
     
                # 에이전트 설정 (사용자가 ui상에서 설정한대로 설정됨)
                config = AgentConfig(
                    session_id=session_id,
                    ollama_url=ollama_url,
                    ollama_model=ollama_model
                )
                print(f"[DEBUG] Config: {config.__dict__}")
                
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
                
                print("[DEBUG] 에이전트 초기화 중...")
                loop.run_until_complete(agent.initialize())
                print("[DEBUG] 에이전트 초기화 완료")
                
                # 세션 상태 저장
                st.session_state.agent = agent
                st.session_state.agent_initialized = True
                st.session_state.agent_tools = [tool.name for tool in agent.all_tools]
                st.session_state.session_id = session_id
                
                st.success("에이전트 초기화 완료!")
                st.rerun()
                
            except Exception as e:
                st.error(f"초기화 실패: {str(e)}")
    
    # 세션 정리 버튼
    if st.button("🧹 MCP 서버 종료"):
        if 'agent' in st.session_state:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(st.session_state.agent.cleanup())
                
                # 세션 상태 정리
                for key in ['agent', 'agent_initialized', 'agent_tools']:
                    if key in st.session_state:
                        del st.session_state[key]
                
                st.success("세션 정리 완료!")
                st.rerun()
                
            except Exception as e:
                st.error(f"세션 정리 실패: {str(e)}")

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
if prompt := st.chat_input("질문을 입력하세요."):
    # 에이전트가 초기화되었는지 확인
    if 'agent_initialized' not in st.session_state or not st.session_state.agent_initialized:
        st.error("먼저 사이드바에서 에이전트를 초기화해주세요.")
        st.stop()
    
    # 사용자 메시지 추가
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 어시스턴트 응답
    with st.chat_message("assistant"):
        with st.spinner("답변 생성 중..."):
            try:
                # 에이전트 쿼리 실행
                print(f"[DEBUG] 질문 받음: {prompt}")
                print(f"[DEBUG] 세션 ID: {st.session_state.session_id}")
                
                # 기존 이벤트 루프 확인 및 사용
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_closed():
                        raise RuntimeError("Loop is closed")
                except RuntimeError:
                    # 필요할 때만 새 루프 생성 
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                print("[DEBUG] 에이전트 쿼리 실행 중...")
                response = loop.run_until_complete(
                    st.session_state.agent.run_query(prompt, st.session_state.session_id)
                )
                print(f"[DEBUG] 응답 받음: {response}")
                
                # 1. JSON 블록 추출: ``` 없이 바로 [ { ... } ] 로 감싸진 경우까지 지원
                json_match = re.search(r'(\[\s*\{.*?\}\s*\])', response, re.DOTALL)

                if json_match:
                    # 2. JSON 문자열 추출 및 제거
                    json_str = json_match.group(1)
                    try:
                        data = json.loads(json_str)
                        df = pd.DataFrame(data)

                        # 3. 자연어 설명 출력 (JSON 제외한 부분만)
                        natural_text = response.replace(json_str, "").strip()
                        natural_text = natural_text.replace("```", "").strip()
                        natural_text = natural_text.replace("json", "").strip()
                        if natural_text:
                            print(f"[DEBUG] {natural_text}")
                            st.markdown(natural_text)

                        # 4. JSON 표 출력
                        st.dataframe(df)

                        st.session_state.messages.append({"role": "assistant", "content": natural_text})
                        st.session_state.messages.append({"role": "dataframe", "content": df})

                    except json.JSONDecodeError as e:
                        st.error(f"❌ JSON 파싱 실패: {e}")
                else:
                    # JSON 블록이 없으면 전체 텍스트만 출력
                    st.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                
                # 어시스턴트 메시지 추가
                # st.session_state.messages.append({"role": "assistant", "content": response})
                
            except Exception as e:
                error_message = f"오류가 발생했습니다: {str(e)}"
                print(f"[DEBUG] 오류 발생: {error_message}")
                import traceback
                traceback.print_exc()
                st.error(error_message)
                st.session_state.messages.append({"role": "assistant", "content": error_message})

# 하단 정보
st.markdown("---")
st.caption("💡 팁: Oracle DB 접근 및 조회, 이전 대화 내역 조회 등의 기능을 사용할 수 있습니다.")
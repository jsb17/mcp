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

from agent_graph import MCPAgent, AgentConfig


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
    # TODO 모델 목록 수정(50번 서버 Ollama 확인)
    model_options = ["qwen3:32b", "gemma3:12b", "gemma3:27b"]
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
    # with st.chat_message(message["role"]):
        if message["role"] == "dataframe":
            st.dataframe(message["content"])
        else:
            st.chat_message(message["role"]).markdown(message["content"])

# 사용자 입력
if prompt := st.chat_input("질문을 입력하세요..."):
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
                
                # st.markdown(response)
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
                            # st.markdown("### 📄 LLM 응답 (설명)")
                            print(f"[DEBUG] {natural_text}")
                            st.markdown(natural_text)

                        # 4. JSON 표 출력
                        # st.markdown("### 📊 결과 테이블")
                        st.dataframe(df)

                        st.session_state.messages.append({"role": "assistant", "content": natural_text})
                        st.session_state.messages.append({"role": "dataframe", "content": df})

                    except json.JSONDecodeError as e:
                        st.error(f"❌ JSON 파싱 실패: {e}")
                else:
                    # JSON 블록이 없으면 전체 텍스트만 출력
                    # st.markdown("### 📄 LLM 응답")
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

# st.markdown("---")
# # 채팅 히스토리 관리
# col1, col2 = st.columns(2)

# with col1:
#     if st.button("📜 채팅 히스토리 조회"):
#         if 'agent_initialized' in st.session_state and st.session_state.agent_initialized:
#             with st.spinner("메모리 서버에서 채팅 히스토리 조회 중..."):
#                 try:
#                     # 기존 이벤트 루프 확인 및 사용
#                     try:
#                         loop = asyncio.get_event_loop()
#                         if loop.is_closed():
#                             raise RuntimeError("Loop is closed")
#                     except RuntimeError:
#                         loop = asyncio.new_event_loop()
#                         asyncio.set_event_loop(loop)
                    
#                     # get_messages 도구를 사용해서 채팅 히스토리 조회
#                     async def get_chat_history():
#                         return await st.session_state.agent.mcp_wrapper.execute_tool(
#                             "get_messages", 
#                             {"session_id": st.session_state.session_id}
#                         )
                    
#                     history_result = loop.run_until_complete(get_chat_history())
#                     print(f"[DEBUG] 채팅 히스토리 조회 결과: {history_result}")
                    
#                     # 결과 파싱 및 표시
#                     try:
#                         # 1. 문자열 결과를 JSON으로 파싱
#                         if isinstance(history_result, str):
#                             history_data = json.loads(history_result)
#                         else:
#                             history_data = history_result
                        
#                         print(f"[DEBUG] 파싱된 히스토리 데이터 타입: {type(history_data)}")
#                         print(f"[DEBUG] 히스토리 데이터 구조: {str(history_data)[:200]}...")
                        
#                         # 2. 데이터 구조 파악 및 메시지 추출
#                         messages = []
                        
#                         if isinstance(history_data, dict):
#                             # 세션 기반 구조인지 확인 {"session_id": [...]}
#                             session_key = st.session_state.session_id
#                             if session_key in history_data:
#                                 messages = history_data[session_key]
#                                 print(f"[DEBUG] 세션 기반 구조: {session_key}에서 {len(messages)}개 메시지")
#                             else:
#                                 # 첫 번째 키의 값을 사용하거나 전체를 메시지로 간주
#                                 if history_data:
#                                     first_key = list(history_data.keys())[0]
#                                     if isinstance(history_data[first_key], list):
#                                         messages = history_data[first_key]
#                                         print(f"[DEBUG] 첫 번째 키 '{first_key}'에서 {len(messages)}개 메시지")
#                                     else:
#                                         # 직접 딕셔너리가 메시지 형태인지 확인
#                                         if "role" in history_data and "content" in history_data:
#                                             messages = [history_data]
#                                             print("[DEBUG] 단일 메시지 구조")
#                         elif isinstance(history_data, list):
#                             messages = history_data
#                             print(f"[DEBUG] 리스트 구조: {len(messages)}개 메시지")
                        
#                         # 3. 메시지 표시
#                         if messages and len(messages) > 0:
#                             st.success(f"총 {len(messages)}개의 메시지를 찾았습니다.")
                            
#                             # 메시지 히스토리를 테이블로 표시
#                             df_data = []
#                             for i, msg in enumerate(messages):
#                                 try:
#                                     # 메시지가 딕셔너리인지 확인
#                                     if isinstance(msg, dict):
#                                         content = str(msg.get("content", "")).strip()
#                                         content_preview = content[:100] + ("..." if len(content) > 100 else "")
                                        
#                                         df_data.append({
#                                             "순번": i + 1,
#                                             "시간": msg.get("timestamp", "N/A"),
#                                             "역할": msg.get("role", "unknown"),
#                                             "내용": content_preview,
#                                             "메시지ID": msg.get("message_id", "N/A")
#                                         })
#                                     else:
#                                         df_data.append({
#                                             "순번": i + 1,
#                                             "시간": "N/A",
#                                             "역할": "unknown",
#                                             "내용": str(msg)[:100] + ("..." if len(str(msg)) > 100 else ""),
#                                             "메시지ID": "N/A"
#                                         })
#                                 except Exception as msg_error:
#                                     print(f"[DEBUG] 메시지 {i} 처리 오류: {msg_error}")
#                                     df_data.append({
#                                         "순번": i + 1,
#                                         "시간": "ERROR",
#                                         "역할": "error",
#                                         "내용": f"메시지 처리 오류: {str(msg_error)}",
#                                         "메시지ID": "ERROR"
#                                     })
                            
#                             if df_data:
#                                 df_history = pd.DataFrame(df_data)
#                                 st.dataframe(df_history, use_container_width=True)
                                
#                                 # 상세 내용 확장 가능한 영역으로 표시
#                                 with st.expander("📝 채팅 히스토리 상세 내용"):
#                                     for i, msg in enumerate(messages):
#                                         try:
#                                             if isinstance(msg, dict):
#                                                 role = msg.get('role', 'unknown')
#                                                 timestamp = msg.get('timestamp', 'N/A')
#                                                 content = str(msg.get('content', ''))
#                                             else:
#                                                 role = 'unknown'
#                                                 timestamp = 'N/A'
#                                                 content = str(msg)
                                                
#                                             st.write(f"**{i+1}. [{role}]** ({timestamp})")
#                                             st.write(content)
#                                             st.divider()
#                                         except Exception as detail_error:
#                                             st.error(f"메시지 {i+1} 표시 오류: {detail_error}")
#                                             st.write(f"원본 데이터: {str(msg)}")
#                                             st.divider()
#                             else:
#                                 st.warning("표시할 수 있는 메시지 데이터가 없습니다.")
#                         else:
#                             st.warning("저장된 채팅 히스토리가 없습니다.")
                            
#                     except json.JSONDecodeError as e:
#                         st.error(f"❌ JSON 파싱 실패: {e}")
#                         with st.expander("원본 데이터 확인"):
#                             st.text(str(history_result))
#                     except Exception as e:
#                         st.error(f"❌ 히스토리 데이터 처리 중 오류: {e}")
#                         with st.expander("디버그 정보"):
#                             st.text(f"데이터 타입: {type(history_result)}")
#                             st.text(f"데이터 내용: {str(history_result)}")
#                             import traceback
#                             st.text("상세 오류:")
#                             st.text(traceback.format_exc())
                        
#                 except Exception as e:
#                     st.error(f"채팅 히스토리 조회 중 오류: {str(e)}")
#                     import traceback
#                     st.text("상세 오류:")
#                     st.text(traceback.format_exc())
#         else:
#             st.warning("MCP 서버가 연결되지 않았습니다.")

# with col2:
#     if st.button("🗑️ 채팅 히스토리 삭제"):
#         st.session_state.messages = []
#         st.success("채팅 히스토리가 삭제되었습니다.")
#         st.rerun()

# 도구 정보 표시 (확장 가능)
# with st.expander("🛠️ 사용 가능한 도구들"):
#     if 'agent_tools' in st.session_state:
#         for tool_name in st.session_state.agent_tools:
#             st.code(tool_name)
#     else:
#         st.info("에이전트를 초기화하면 사용 가능한 도구 목록이 표시됩니다.")

# 하단 정보
st.markdown("---")
st.caption("💡 팁: Oracle DB 접근 및 조회, 이전 대화 내역 조회 등의 기능을 사용할 수 있습니다.")
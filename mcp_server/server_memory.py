"""
Memory MCP 서버 - 사용자의 대화 이력을 저장하고 관리
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict

from fastmcp import FastMCP


# 로그 레벨 및 포맷 설정
# logging.basicConfig(level=logging.INFO, format="🔧 [%(levelname)s] %(message)s")


# 하나의 메세지에 대한 데이터 클래스
@dataclass
class ChatMessage:
    message_id: str 
    timestamp: str
    role: str       # 'user' or 'assistant'
    content: str
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

# 메모리 저장소 (현재: 메모리 변수에 저장. 단, 세션이 끝나면 모든 데이터 휘발됨)
# TODO 추후 파일 or DB 형태로 변환 
memory_storage: Dict[str, List[ChatMessage]] = {}


# MCP 서버 객체 생성
mcp = FastMCP(name="memory")


# MCP 서버 도구 추가
@mcp.tool()
def save_message(
    session_id: str,
    role: str,
    content: str,
    message_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    하나의 메세지를 저장합니다.
    """
    try:
        if not message_id:
            message_id = f"{session_id}_{len(memory_storage.get(session_id, []))}"
            timestamp = datetime.now().isoformat()

            message = ChatMessage(
                message_id=message_id,
                timestamp=timestamp,
                role=role,
                content=content
            )

            if session_id not in memory_storage:
                memory_storage[session_id] = []

            memory_storage[session_id].append(message)
            # logging.info(f'[DEBUG] Memory Storage: {memory_storage}')
            
            return memory_storage
            # return {
            #     "success": True,
            #     "message": "메세지가 저장되었습니다",
            #     "data": asdict(message)
            # }

    except Exception as e:
        return {
            "success": False,
            "message": f"메세지 저장 실패: {str(e)}"
        }


@mcp.tool()
def get_messages(
    session_id: str,
    limit: Optional[int] = 10
) -> Dict[str, Any]:
    """
    저장된 대화 메세지 중 최신 10개를 조회합니다.
    """
    try:
        if session_id not in memory_storage:
            return {
                "success": True,
                "message": "해당 세션의 메세지가 없습니다",
                "data": []
            }

        messages = memory_storage[session_id]

        # 최신 limit개의 메세지만 조회 
        if limit:
            messages = messages[-limit:]

        return {
            "success": True,
            "message": f"{len(messages)}개의 메세지를 찾았습니다",
            "data": [asdict(msg) for msg in messages]
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"메세지 조회 실패: {str(e)}",
            "data": []
        }


@mcp.tool()
def search_messages(
    session_id: str,
    keyword: str,         # 사용자 질문에서의 LLM이 직접 키워드 추출   # TODO 더 많은 테스트 필요
    limit: Optional[int] = 10
) -> Dict[str, Any]:
    """
    저장된 대화 메세지 중 질문 키워드를 포함하는 최신 10개를 조회합니다. 
    """
    try:
        if session_id not in memory_storage:
            return {
                "success": True,
                "message": "해당 세션의 메세지가 없습니다",
                "data": []
            }

        messages = memory_storage[session_id]

        # 저장된 대화 메세지 중 keyword가 포함된 메세지만 검색
        matching_messages = [
            msg for msg in messages
            if keyword.lower() in msg.content.lower()
        ]

        # 검색된 메세지 중 최신 limit개만 조회 
        if limit:
            matching_messages = matching_messages[-limit:]

        return {
            "success": True,
            "message": f"'{keyword}' 키워드로 {len(matching_messages)}개의 메세지를 찾았습니다",
            "data": [asdict(msg) for msg in matching_messages]
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"메세지 검색 실패: {str(e)}",
            "data": []
        }


# 추후 사용
# @mcp.tool() 
# def list_sessions() -> Dict[str, Any]:
#     """
#     모든 세션 목록을 조회합니다.
#     """
#     try:
#         session_info = {}
#         for session_id, messages in memory_storage.items():
#             session_info[session_id] = {
#                 "message_count": len(messages),
#                 "last_message_time": messages[-1].timestamp if messages else None
#             }

#         return {
#             "success": True,
#             "message": f"{len(session_info)}개의 세션을 찾았습니다",
#             "sessions": session_info
#         }

#     except Exception as e:
#         return {
#             "success": False,
#             "message": f"세션 목록 조회 실패: {str(e)}",
#             "sessions": {}
#         }


# MCP 서버 실행 
if __name__ == "__main__":
    mcp.run(transport="stdio") 
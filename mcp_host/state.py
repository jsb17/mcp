"""
Agent 상태 정의
"""

from typing import Dict, List, TypedDict, Optional
from langchain_core.messages import HumanMessage, AIMessage


class AgentState(TypedDict):
    messages: List[HumanMessage | AIMessage]
    question: str
    tool_calls: Optional[List[Dict]]  # MCP 서버로부터 호출된 도구들 
    executed_results: List[Dict]
    dataframe: List[Dict]
    final_answer: str
    session_id: str
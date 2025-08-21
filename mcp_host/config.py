"""
Agent 설정 관리
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv
from dataclasses import dataclass


load_dotenv()
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MCP_CONFIG_FILE_PATH = Path(os.path.join(BASE_DIR, os.getenv("MCP_CONFIG_FILE_PATH")))


@dataclass
class AgentConfig:
    session_id: str = "default"
    ollama_url: str = os.getenv("OLLAMA_URL")
    ollama_model: str = os.getenv("OLLAMA_MODEL")
    mcp_servers_config = None

    def __post_init__(self):
        if self.mcp_servers_config is None:
            if MCP_CONFIG_FILE_PATH.exists():
                with MCP_CONFIG_FILE_PATH.open("r", encoding="utf-8") as f:
                    self.mcp_servers_config = json.load(f)
                
                # 환경변수로 원격 서버 URL 오버라이드
                oracle_url = os.getenv("MCP_ORACLE_SERVER_URL")
                memory_url = os.getenv("MCP_MEMORY_SERVER_URL")
                
                if oracle_url:
                    self.mcp_servers_config["oracle-db"]["url"] = oracle_url
                    print(f"🔗 Oracle DB 서버 URL 환경변수로 설정: {oracle_url}")
                
                if memory_url:
                    self.mcp_servers_config["memory"]["url"] = memory_url
                    print(f"🔗 Memory 서버 URL 환경변수로 설정: {memory_url}")
                    
            else: 
                raise FileNotFoundError(f"❌ MCP 서버 설정 파일이 없습니다: {MCP_CONFIG_FILE_PATH}")

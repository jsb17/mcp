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
            else: 
                raise FileNotFoundError(f"❌ MCP 서버 설정 파일이 없습니다: {MCP_CONFIG_FILE_PATH}")

"""
공통 유틸리티 함수 모음
"""

import os
import re
import json
from pathlib import Path
from typing import List, Dict

import oracledb
from dotenv import load_dotenv


def get_oracle_db_connection():
    """
    Oracle DB에 접속 
    """
    
    load_dotenv()

    # Oracle DB 관련 설정
    ORACLE_USER=os.getenv("ORACLE_USER")
    ORACLE_PASSWORD=os.getenv("ORACLE_PASSWORD")
    ORACLE_DSN=os.getenv("ORACLE_DSN")

    conn = oracledb.connect(
        user=ORACLE_USER,
        password=ORACLE_PASSWORD,
        dsn=ORACLE_DSN
    )
    return conn


def get_generate_sql_tool_prompt(natural_query: str, schema_info: str) -> str:
    """
    Oracle DB MCP 서버 - generate_sql 도구에서 사용되는 Text to SQL 프롬프트
    """
    return (
        "당신은 사용자의 자연어 질문을 oracle 쿼리로 변환하는 시스템입니다.\n"
        "아래의 DB Schema를 참고하여 사용자의 자연어 질문을 1개의 oracle 쿼리로 변환하세요.\n\n"
        "DB Schema:\n" + schema_info + "\n\n"
        "자연어 질문:\n" + natural_query + "\n\n"
        "불필요한 설명 없이 변환된 1개의 oracle 쿼리만 답변으로 반환하세요:\n"
        "(단, oracle에서는 AS를 쓰면 문법 오류가 나니 사용하지 마십시오.)"
    )


def strip_code_block(text: str) -> str:
    """
    ```json ... ``` 또는 ``` ... ``` 로 감싼 코드 블록의 내용만 추출
    코드 블록이 없으면 원문 반환
    """
    pattern = r"```(?:\w+)?\s*([\s\S]*?)\s*```"
    match = re.search(pattern, text.strip())
    if match:
        return match.group(1).strip()
    return text.strip()


def strip_think_block(text: str) -> str:
    """
    qwen 모델을 위한 별도 처리 함수 -  <think></think> 태그 제거
    """
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def clean_sql_query(raw_sql: str) -> str:
    """
    SQL 문자열에서 개행 문자와 세미콜론을 제거하고 한 줄로 정리
    """
    # 1. 개행 문자 제거 + 여러 공백을 하나로 압축
    one_liner = " ".join(raw_sql.strip().split())

    # 2. 끝에 세미콜론 제거
    return one_liner.rstrip(";")
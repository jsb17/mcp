import os
import json
import logging
import asyncio
from typing import Any, Dict, List

import aiohttp
import oracledb
from dotenv import load_dotenv
from fastmcp import FastMCP

# 로그 레벨 및 포맷 설정
# logging.basicConfig(level=logging.INFO, format="🔧 [%(levelname)s] %(message)s")

load_dotenv()

# Oracle DB 관련 설정
ORACLE_USER=os.getenv("ORACLE_USER")
ORACLE_PASSWORD=os.getenv("ORACLE_PASSWORD")
ORACLE_DSN=os.getenv("ORACLE_DSN")

# Ollama 서버 관련 설정
OLLAMA_URL = os.getenv("OLLAMA_URL") 
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")


# MCP 서버 객체 생성 
mcp = FastMCP(name="oracle-db") 


# Utility
def get_connection():
    """
    Oracle DB에 접속 
    """
    conn = oracledb.connect(
        user=ORACLE_USER,
        password=ORACLE_PASSWORD,
        dsn=ORACLE_DSN
    )
    return conn

def strip_code_block(text: str) -> str:
    """
    ```json ... ``` 또는 ``` ... ``` 감싼 부분 제거
    """
    if text.strip().startswith("```"):
        return "\n".join(line for line in text.strip().splitlines() if not line.strip().startswith("```"))
    return text

def clean_sql_query(raw_sql: str) -> str:
    """
    SQL 문자열에서 개행 문자와 세미콜론을 제거하고 한 줄로 정리
    """
    # 1. 개행 문자 제거 + 여러 공백을 하나로 압축
    one_liner = " ".join(raw_sql.strip().split())

    # 2. 끝에 세미콜론 제거
    return one_liner.rstrip(";")


# MCP 서버 도구 추가
@mcp.tool 
def get_schema_info() -> str:
    """
    View the schema of all tables owned by the current account for text-to-SQL conversion.
    """
    schema_info = {"tables": {}}

    conn = get_connection()
    cursor = conn.cursor()

    # 현재 계정이 소유한 모든 테이블 목록 조회
    cursor.execute("""
        SELECT table_name
        FROM user_tables
        ORDER BY table_name
    """)
    tables = cursor.fetchall()
    
    for table in tables:
        table_name = table[0]
        # 각 테이블의 컬럼 정보 조회
        cursor.execute("""
            SELECT 
                column_name,
                data_type,
                data_length,
                data_precision,
                data_scale,
                nullable
            FROM user_tab_columns
            WHERE table_name = :table_name 
        """, {"table_name": table_name})
        columns = cursor.fetchall()

        schema_info["tables"][table_name] = {
            "columns": [
                {
                    "name": col[0],
                    "type": col[1],
                    "length": col[2],
                    "precision": col[3],
                    "scale": col[4],
                    "nullable": col[5] == 'Y'
                }
                for col in columns
            ]
        }
    
    cursor.close()
    conn.close()

    return json.dumps(schema_info, indent=2) # Dict 타입의 schema_info를 JSON 문자열로 변환


@mcp.tool 
async def generate_sql(natural_query: str, schema_info: str) -> str: 
    """
    Convert natural language question to SQL query with LLM.
    """
    async with aiohttp.ClientSession() as session:
        system_prompt = (
            "당신은 사용자의 자연어 질문을 oracle 쿼리로 변환하는 시스템입니다.\n"
            "아래의 DB Schema를 참고하여 사용자의 자연어 질문을 oracle 쿼리로 변환하세요.\n\n"
            "DB Schema:\n" + schema_info + "\n\n"
            "자연어 질문:\n" + natural_query + "\n\n"
            "불필요한 설명 없이 변환된 oracle 쿼리만 답변으로 반환하세요:\n"
        )
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt}
            ],
            "stream": False
        }
        async with session.post(f"{OLLAMA_URL}/v1/chat/completions", json=payload) as resp:
            data = await resp.json()
            generated_sql = data["choices"][0]["message"]["content"]
            # logging.info(f'[DEBUG] Generated SQL: {generated_sql}')

            cleaned_sql = strip_code_block(generated_sql)
            cleaned_sql = clean_sql_query(cleaned_sql)

            return cleaned_sql 


@mcp.tool  
def validate_sql(sql: str) -> Dict[str, Any]:
    """
    In Oracle, SQL syntax validity is checked using the EXPLAIN PLAN FOR statement.
    This attempts to parse the SQL statement.
    It does not actually execute the statement, but it can detect syntax errors.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try: 
        cursor.execute("EXPLAIN PLAN FOR " + sql)  # 실제 실행은 안 함, 문법만 검사
        return {"valid": True, "message": "SQL 유효함", "sql": sql}
    
    except Exception as e:
        return {"valid": False, "message": str(e), "sql": sql}
    

@mcp.tool 
def execute_sql(exec_sql: str) -> list:
    """
    Executes a SELECT query on the Oracle database and returns the results.
    INSERT, UPDATE, and DDL statements are not supported.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(exec_sql)

        # SELECT 문이 아닌 경우는 건너뜀
        if cursor.description is None:
            return {"error": "SELECT 문만 지원합니다."}
        
        columns: List[str] = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

        result = [dict(zip(columns, row)) for row in rows]

        cursor.close()
        conn.close()
        return result
    
    except Exception as e:
        cursor.close()
        conn.close()
        return [{"error": str(e), "exec_sql": exec_sql}]


# MCP 서버 실행 
if __name__ == "__main__": 
    mcp.run(transport="stdio")  
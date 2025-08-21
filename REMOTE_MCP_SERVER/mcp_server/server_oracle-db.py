"""
Oracle DB MCP 서버 - Oracle DB에 접근 및 조작
"""

import os
import sys
import json
from typing import Any, Dict, List

import aiohttp # 비동기 HTTP 클라이언트(Ollama API 호출용)
from fastmcp import FastMCP
from dotenv import load_dotenv

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.utils import get_oracle_db_connection, get_generate_sql_tool_prompt, strip_code_block, strip_think_block, clean_sql_query


# MCP 서버 객체 생성 
mcp = FastMCP(name="oracle-db") 


# MCP 서버 도구 추가
@mcp.tool 
def get_schema_info() -> str:
    """
    Text-to-SQL 변환을 위해 현재 계정이 소유한 모든 테이블의 스키마를 로드합니다.
    """
    schema_info = {"tables": {}}

    conn = get_oracle_db_connection()
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
    LLM이 schema를 참조하여 자연어 질문을 SQL 쿼리로 변환합니다.
    """
    load_dotenv()

    # Ollama 서버 관련 설정
    OLLAMA_URL = os.getenv("OLLAMA_URL") 
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")

    async with aiohttp.ClientSession() as session:
        system_prompt = get_generate_sql_tool_prompt(natural_query, schema_info)
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt}
            ],
            "options": {
                "temperature": 0,     # 무작위성 제거
                "top_p": 1,           # 확률 컷오프 제거
                "repeat_penalty": 1   # 반복 억제 영향 최소화
            },
            "stream": False
        }
        async with session.post(f"{OLLAMA_URL}/v1/chat/completions", json=payload) as resp:
            data = await resp.json()
            generated_sql = data["choices"][0]["message"]["content"]
            # logging.info(f'[DEBUG] Generated SQL: {generated_sql}')

            cleaned_sql = strip_code_block(generated_sql)
            cleaned_sql = strip_think_block(cleaned_sql) # qwen 모델 특화
            cleaned_sql = clean_sql_query(cleaned_sql)

            return cleaned_sql 


@mcp.tool  
def validate_sql(sql: str) -> Dict[str, Any]:
    """
    Oracle DB에서 EXPLAIN PLAN FOR 문을 사용해 SQL 문법 유효성을 검증합니다.
    """
    # 환경변수 재로드 (MCP 도구 실행 시점에서)
    oracle_user = os.getenv("ORACLE_USER") or "sebin"
    oracle_password = os.getenv("ORACLE_PASSWORD") or "sebin123" 
    oracle_dsn = os.getenv("ORACLE_DSN") or "192.168.25.121:1521/FREEPDB1"
    
    conn = get_oracle_db_connection()
    cursor = conn.cursor()

    try: 
        cursor.execute("EXPLAIN PLAN FOR " + sql)  # 실제 실행은 안 함, 문법만 검사
        return {"valid": True, "message": "SQL 유효함", "sql": sql} 
    
    except Exception as e:
        return {"valid": False, "message": str(e), "sql": sql} # 서버가 결과를 JSON-RPC 응답으로 직렬화 => Python False → JSON false로 변환
    

@mcp.tool 
def execute_sql(exec_sql: str) -> list:
    """
    Oracle DB에서 SELECT 쿼리를 실행하고 결과를 반환합니다.(INSERT, UPDATE 및 DDL 지원 X)
    """
    conn = get_oracle_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(exec_sql)

        # SELECT 문이 아닌 경우는 건너뜀
        if cursor.description is None:
            return {"error": "SELECT 문만 지원합니다."}
        
        columns: List[str] = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

        if rows:
            result = [dict(zip(columns, row)) for row in rows]
        else:
            result = ["조회된 데이터가 없습니다."]

        cursor.close()
        conn.close()
        return result
    
    except Exception as e:
        cursor.close()
        conn.close()
        return [{"error": str(e), "exec_sql": exec_sql}]


# MCP 서버 실행 
if __name__ == "__main__": 
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0", 
        port=8000,
        path="/mcp",        # MCP 서버 엔드포인트 경로
        log_level="debug",  # debug 수준의 로그 출력 
    )  
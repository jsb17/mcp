import oracledb

def get_connection(user: str, pw: str, dsn: str):
    """
    Oracle DB에 접속 
    """
    conn = oracledb.connect(
        user=user,
        password=pw,
        dsn=dsn
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

def to_ollama_tool_description(tool) -> str:
    """
    Ollama LLM에게 전달(Prompt에 삽입)하기 위한, MCP 도구 관련 Description 생성
    """
    raw_schema = (
        getattr(tool, "inputSchema", None)
        or getattr(tool, "input_schema", None)
        or getattr(tool, "parameters", None)
    )

    props = {}
    required = []

    if isinstance(raw_schema, dict):
        props = raw_schema.get("properties", {})
        required = raw_schema.get("required", [])
    elif hasattr(raw_schema, "model_json_schema"):
        schema = raw_schema.model_json_schema()
        props = schema.get("properties", {})
        required = schema.get("required", [])
    elif isinstance(raw_schema, list):  # list of dicts
        props = {p["name"]: {"type": p["type"], "description": p.get("description", "")} for p in raw_schema}
        required = [p["name"] for p in raw_schema if p.get("required", True)]

    lines = [f"함수 이름: {tool.name}"]
    lines.append(f"설명: {getattr(tool, 'description', '')}")

    if props:
        lines.append("인자 설명:")
        for name, info in props.items():
            type_ = info.get("type", "unknown")
            desc = info.get("description", "")
            req = " (필수)" if name in required else " (선택)"
            lines.append(f"- {name} ({type_}){req}: {desc}")

    return "\n".join(lines)
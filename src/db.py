from sqlite3 import Connection, Cursor

from .config import configuration

databases = configuration.get("databases", {})
database_path = databases.get("memory", "./data/agent.db")


def get_db_connection() -> tuple[Connection, Cursor]:
    conn = Connection(database_path)
    return conn, conn.cursor()


def init_db():
    conn, cursor = get_db_connection()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        content TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        done BOOLEAN DEFAULT FALSE,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


def new_memory(content: str):
    conn, cursor = get_db_connection()
    cursor.execute("INSERT INTO memory (content) VALUES (?)", (content,))
    conn.commit()
    conn.close()

def delete_memory(memory_id: int):
    conn, cursor = get_db_connection()
    cursor.execute("DELETE FROM memory WHERE id = ?", (memory_id,))
    conn.commit()
    conn.close()

def get_memories() -> list[dict]:
    conn, cursor = get_db_connection()
    cursor.execute("SELECT id, content, timestamp FROM memory ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    conn.close()

    return [{"id": row[0], "mem": row[1], "time": row[2]} for row in rows]

def overwrite_memory(memory_id: int, new_content: str):
    conn, cursor = get_db_connection()
    cursor.execute("UPDATE memory SET content = ?, timestamp = CURRENT_TIMESTAMP WHERE id = ?", (new_content, memory_id))
    conn.commit()
    conn.close()

def new_skill(name: str, content: str):
    conn, cursor = get_db_connection()
    cursor.execute("INSERT INTO skills (name, content) VALUES (?, ?)", (name, content))
    conn.commit()
    conn.close()

def delete_skill(skill_id: int):
    conn, cursor = get_db_connection()
    cursor.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
    conn.commit()
    conn.close()

def get_skills() -> list[dict[str, str | int]]:
    conn, cursor = get_db_connection()
    cursor.execute("SELECT id, name, content, timestamp FROM skills ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    conn.close()

    return [{"id": row[0], "name": row[1], "content": row[2]} for row in rows]

def overwrite_skill(skill_id: int, new_name: str, new_content: str):
    conn, cursor = get_db_connection()
    cursor.execute("UPDATE skills SET name = ?, content = ?, timestamp = CURRENT_TIMESTAMP WHERE id = ?", (new_name, new_content, skill_id))
    conn.commit()
    conn.close()

def new_todo(content: str):
    conn, cursor = get_db_connection()
    cursor.execute("INSERT INTO todos (content) VALUES (?)", (content,))
    conn.commit()
    conn.close()

def delete_todos():
    conn, cursor = get_db_connection()
    cursor.execute("DELETE FROM todos WHERE done = 1")
    conn.commit()
    conn.close()

def get_todos() -> list[dict]:
    conn, cursor = get_db_connection()
    cursor.execute("SELECT id, content, done, timestamp FROM todos ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    conn.close()

    return [{"id": row[0], "content": row[1], "done": "yes" if bool(row[2]) else "no"} for row in rows]

def tick_todo(todo_id: int, done: bool):
    conn, cursor = get_db_connection()
    cursor.execute("UPDATE todos SET done = ?, timestamp = CURRENT_TIMESTAMP WHERE id = ?", (done, todo_id))
    conn.commit()
    conn.close()

init_db()

import json, sqlite3, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS workflows (id TEXT PRIMARY KEY, name TEXT NOT NULL, graph_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, workflow_id TEXT, status TEXT, started_at TEXT, finished_at TEXT, token_in INTEGER DEFAULT 0, token_out INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0, error_json TEXT);
CREATE TABLE IF NOT EXISTS node_runs (id TEXT PRIMARY KEY, run_id TEXT, node_id TEXT, fingerprint TEXT, status TEXT, duration_ms INTEGER, cache_hit INTEGER, code TEXT, error TEXT, output_path TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value_encrypted BLOB, updated_at TEXT);
CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, workflow_id TEXT, graph_json TEXT, created_at TEXT);
'''

def now(): return datetime.now(timezone.utc).isoformat()

def init_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db: db.executescript(SCHEMA)

@contextmanager
def db(path):
    con = sqlite3.connect(path); con.row_factory = sqlite3.Row
    try:
        yield con; con.commit()
    finally: con.close()

def create_workflow(path, name, graph=None):
    ident = str(uuid.uuid4()); stamp = now(); graph = graph or {"nodes": [], "edges": []}
    with db(path) as con: con.execute("INSERT INTO workflows VALUES(?,?,?,?,?)", (ident, name, json.dumps(graph), stamp, stamp))
    return {"id": ident, "name": name, "graph": graph, "created_at": stamp, "updated_at": stamp}

def list_workflows(path):
    with db(path) as con: return [dict(x) for x in con.execute("SELECT id,name,created_at,updated_at FROM workflows ORDER BY updated_at DESC")]

def get_workflow(path, ident):
    with db(path) as con: row = con.execute("SELECT * FROM workflows WHERE id=?", (ident,)).fetchone()
    if not row: return None
    value = dict(row); value["graph"] = json.loads(value.pop("graph_json")); return value

def save_workflow(path, ident, name, graph):
    stamp = now()
    with db(path) as con:
        con.execute("UPDATE workflows SET name=?,graph_json=?,updated_at=? WHERE id=?", (name, json.dumps(graph), stamp, ident))
        con.execute("INSERT INTO snapshots VALUES(?,?,?,?)", (str(uuid.uuid4()), ident, json.dumps(graph), stamp))
        con.execute("DELETE FROM snapshots WHERE workflow_id=? AND id NOT IN (SELECT id FROM snapshots WHERE workflow_id=? ORDER BY created_at DESC LIMIT 10)", (ident, ident))

def delete_workflow(path, ident):
    with db(path) as con: return con.execute("DELETE FROM workflows WHERE id=?", (ident,)).rowcount

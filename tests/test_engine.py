import pytest
from app.engine import execute, fingerprint, graph_order, precheck

def node(i,t): return {"id":i,"type":t,"data":{"params":{}}}
def test_fingerprint_is_canonical():
    one={"type":"filter","data":{"params":{"a":1,"b":2}}}; two={"type":"filter","data":{"params":{"b":2,"a":1}}}
    assert fingerprint(one,[]) == fingerprint(two,[])
def test_cycle_is_rejected():
    graph={"nodes":[node("a","preview"),node("b","preview")],"edges":[{"source":"a","target":"b"},{"source":"b","target":"a"}]}
    with pytest.raises(ValueError): graph_order(graph)
def test_precheck_returns_all_errors_without_key():
    graph={"nodes":[node("a","ai_clean")],"edges":[]}
    issues=precheck(graph,False); codes={x['code'] for x in issues}
    assert "missing_input" in codes and "required_param" in codes and "api_key_missing" in codes

def test_ai_clean_executes_generated_code_in_sandbox(tmp_path):
    source=tmp_path/'dirty.csv'; source.write_text('name,value\na,1\na,1\nb,\n')
    graph={"nodes":[
        {"id":"source","type":"file_input","data":{"params":{"path":str(source)}}},
        {"id":"clean","type":"ai_clean","data":{"params":{"intent":"去重并删除空值","model":"test-model"}}},
    ],"edges":[{"source":"source","sourceHandle":"table_out","target":"clean","targetHandle":"table_in"}]}
    calls=[]
    def generator(node_type,params,df):
        calls.append((node_type,params['model'],len(df)))
        return {"code":"result = df.dropna().drop_duplicates()","explanation":"去重并删除空值"}
    _,outputs=execute(graph,tmp_path,lambda *args:None,configured=True,ai_generator=generator)
    assert calls==[("ai_clean","test-model",3)]
    assert outputs['clean'].to_dict('records')==[{"name":"a","value":1.0}]

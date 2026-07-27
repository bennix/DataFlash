from app import create_app

def test_nodes_and_workflow_lifecycle(tmp_path):
    app=create_app({"TESTING":True,"DATABASE":str(tmp_path/'db.sqlite'),"CACHE_DIR":str(tmp_path/'cache'),"SECRET_DIR":str(tmp_path/'secret')}); c=app.test_client()
    assert c.get('/api/nodes').status_code == 200
    made=c.post('/api/workflows',json={"name":"测试"}).get_json(); assert c.get('/api/workflows/'+made['id']).status_code==200
    assert c.delete('/api/workflows/'+made['id']).status_code==204
def test_precheck_refuses_invalid_run(tmp_path):
    app=create_app({"TESTING":True,"DATABASE":str(tmp_path/'db.sqlite'),"CACHE_DIR":str(tmp_path/'cache'),"SECRET_DIR":str(tmp_path/'secret')}); c=app.test_client()
    graph={"nodes":[{"id":"x","type":"ai_clean","data":{"params":{}}}],"edges":[]}
    assert c.post('/api/precheck',json={"graph":graph}).status_code==422
    assert c.post('/api/run',json={"graph":graph}).status_code==422

def test_run_stream_populates_node_preview(tmp_path):
    source=tmp_path/'sample.csv'; source.write_text('name,value\na,1\nb,2\n')
    app=create_app({"TESTING":True,"DATABASE":str(tmp_path/'db.sqlite'),"CACHE_DIR":str(tmp_path/'cache'),"SECRET_DIR":str(tmp_path/'secret')}); c=app.test_client()
    graph={"nodes":[{"id":"source","type":"file_input","data":{"params":{"path":str(source)}}}],"edges":[]}
    started=c.post('/api/run',json={"graph":graph})
    assert started.status_code==200
    run_id=started.get_json()['run_id']
    stream=c.get(f'/api/run/{run_id}/stream').get_data(as_text=True)
    assert 'event: node_start' in stream
    assert 'event: node_log' in stream
    assert 'event: node_done' in stream
    preview=c.get(f'/api/preview/{run_id}/source')
    assert preview.status_code==200
    assert preview.get_json()['rows'][0] == {"name":"a","value":1}

def test_preview_node_passes_through_upstream_table(tmp_path):
    source=tmp_path/'sample.csv'; source.write_text('name,value\na,1\nb,2\n')
    app=create_app({"TESTING":True,"DATABASE":str(tmp_path/'db.sqlite'),"CACHE_DIR":str(tmp_path/'cache'),"SECRET_DIR":str(tmp_path/'secret')}); c=app.test_client()
    graph={"nodes":[
        {"id":"source","type":"file_input","data":{"params":{"path":str(source)}}},
        {"id":"preview","type":"preview","data":{"params":{}}},
    ],"edges":[{"id":"edge","source":"source","sourceHandle":"table_out","target":"preview","targetHandle":"input"}]}
    started=c.post('/api/run',json={"graph":graph}); assert started.status_code==200
    run_id=started.get_json()['run_id']; c.get(f'/api/run/{run_id}/stream').get_data(as_text=True)
    result=c.get(f'/api/preview/{run_id}/preview')
    assert result.status_code==200
    assert result.get_json()['type']=='table'
    assert result.get_json()['rows'][1]=={"name":"b","value":2}

def test_preview_report_markdown_not_treated_as_filepath(tmp_path):
    app=create_app({"TESTING":True,"DATABASE":str(tmp_path/'db.sqlite'),"CACHE_DIR":str(tmp_path/'cache'),"SECRET_DIR":str(tmp_path/'secret')}); c=app.test_client()
    from app.api import runs
    run_id="report-run"
    md="# 数据分析报告\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    runs[run_id]={"outputs":{"report":md},"output_paths":{}}
    preview=c.get(f'/api/preview/{run_id}/report')
    assert preview.status_code==200
    body=preview.get_json()
    assert body["type"]=="markdown"
    assert body["text"].startswith("# 数据分析报告")

def test_preview_figure_and_file(tmp_path):
    app=create_app({"TESTING":True,"DATABASE":str(tmp_path/'db.sqlite'),"CACHE_DIR":str(tmp_path/'cache'),"SECRET_DIR":str(tmp_path/'secret'),"AI_MOCK":True}); c=app.test_client()
    from app.api import runs
    run_id="fig-run"
    pdf=tmp_path/'cache'/'out.pdf'; pdf.parent.mkdir(parents=True, exist_ok=True); pdf.write_bytes(b'%PDF-1.4 fake')
    runs[run_id]={
        "outputs":{
            "chart":{"data":[{"type":"bar","x":[1],"y":[2]}],"layout":{"title":"t"}},
            "export":{"path":str(pdf)},
        },
        "output_paths":{},
    }
    fig=c.get(f'/api/preview/{run_id}/chart').get_json()
    assert fig['type']=='figure'
    assert fig['figure']['data'][0]['type']=='bar'
    file_meta=c.get(f'/api/preview/{run_id}/export').get_json()
    assert file_meta['type']=='file'
    assert file_meta['format']=='pdf'
    assert file_meta['file_url'].endswith('/file')
    raw=c.get(file_meta['file_url'])
    assert raw.status_code==200
    assert raw.data.startswith(b'%PDF')

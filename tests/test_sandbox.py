import pandas as pd
from app.sandbox import run_dataframe

def test_sandbox_writes_only_result(tmp_path):
    source=tmp_path/'in.parquet'; target=tmp_path/'out.parquet'; pd.DataFrame({'a':[1,2]}).to_parquet(source)
    run_dataframe(source,target,"result = df.assign(b=df['a'] * 2)")
    assert list(pd.read_parquet(target)['b']) == [2,4]

def test_sandbox_supports_safe_cleaning_builtins(tmp_path):
    source=tmp_path/'in.parquet'; target=tmp_path/'out.parquet'
    pd.DataFrame({'Sex':[' Female ','MALE'],'Age':[20.0,None]}).to_parquet(source)
    code="""
result = df.copy()
result['Sex'] = result['Sex'].astype(str).str.strip().str.lower()
missing_count = len(result[result['Age'].isna()])
result['missing_count'] = int(missing_count)
"""
    run_dataframe(source,target,code)
    result=pd.read_parquet(target)
    assert result['Sex'].tolist()==['female','male']
    assert result['missing_count'].tolist()==[1,1]

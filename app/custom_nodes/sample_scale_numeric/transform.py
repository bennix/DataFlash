# Scale selected numeric columns by params["factor"] (default 1.0).
# Available: df (input table), params (dict). Assign result.
cols = params.get("columns") or []
factor = params.get("factor")
if factor is None or factor == "":
    factor = 1.0
factor = float(factor)

out = df.copy()
for col in cols:
    if col in out.columns:
        out[col] = out[col] * factor
result = out

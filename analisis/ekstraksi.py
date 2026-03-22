import pandas as pd
from pathlib import Path

base = Path(__file__).resolve().parent
source = base / "aveta.json"
out = base / "aveta.csv"

if not source.exists():
    raise FileNotFoundError(f"Input tidak ditemukan: {source}")

data = pd.json_normalize(pd.read_json(source))
data.to_csv(out, index=False)
print(f"Sukses: {out}")
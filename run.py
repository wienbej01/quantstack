
import pandas as pd, pathlib
path = pathlib.Path("/home/jacobw/quantstack/run/sip_membership/trade_date=2024-05-31")
df = pd.read_parquet(next(path.glob("*.parquet")))
print("SIP symbols:", df[df["is_sip"]]["symbol"].head(20).tolist())
print("Count:", int(df["is_sip"].sum()))

import os
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# --------------------------------------------------
# 1. Load configuration
# --------------------------------------------------
load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
EXCEL_PATH = os.getenv("EXCEL_PATH")
SHEET_NAME = os.getenv("SHEET_NAME")

# --------------------------------------------------
# 2. Connect to PostgreSQL
# --------------------------------------------------
database_url = (
    f"postgresql+psycopg://"
    f"{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)
engine = create_engine(database_url)

# --------------------------------------------------
# 3. Read the latest Excel Sales Tracker
# --------------------------------------------------
excel_file = Path(EXCEL_PATH)
df = pd.read_excel(
    excel_file,
    sheet_name=SHEET_NAME
)

# Standardise column names
df.columns = (
    df.columns
      .str.strip()
      .str.lower()
      .str.replace(" ", "_")
)

# Convert order date
df["order_date"] = pd.to_datetime(
    df["order_date"]
).dt.date

# Keep Order ID consistent for comparison
df["order_id"] = (
    df["order_id"]
      .astype(str)
      .str.strip()
)

# --- ADD THIS: Clean currency columns for PostgreSQL NUMERIC compatibility ---
for col in ["unit_price", "sales_amount"]:
    if col in df.columns:
        df[col] = (
            df[col]
              .astype(str)
              .str.replace("$", "", regex=False)
              .str.replace(",", "", regex=False)
              .str.strip()
        )
        df[col] = pd.to_numeric(df[col], errors="coerce")
# ----------------------------------------------------------------------------

# Add source metadata
df["source_file"] = excel_file.name

# --------------------------------------------------
# 4. Read existing Order IDs from PostgreSQL
# --------------------------------------------------
existing_orders_query = text("""
    SELECT DISTINCT order_id
    FROM raw_sales_tracker
""")

existing_orders = pd.read_sql(
    existing_orders_query,
    engine
)

existing_orders["order_id"] = (
    existing_orders["order_id"]
      .astype(str)
      .str.strip()
)

existing_order_ids = set(
    existing_orders["order_id"]
)

# --------------------------------------------------
# 5. Keep only new sales
# --------------------------------------------------
new_sales = df[
    ~df["order_id"].isin(existing_order_ids)
].copy()

print(f"Rows in Excel: {len(df)}")
print(f"Rows already in PostgreSQL: {len(existing_order_ids)}")
print(f"New rows found: {len(new_sales)}")

# --------------------------------------------------
# 6. Load only new records
# --------------------------------------------------
if new_sales.empty:
    print("No new sales to load.")
else:
    new_sales.to_sql(
        name="raw_sales_tracker",
        con=engine,
        if_exists="append",
        index=False
    )
    print(f"{len(new_sales)} new sales loaded successfully.")
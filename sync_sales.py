import hashlib
import os
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# --------------------------------------------------
# 1. Load configuration & Connect
# --------------------------------------------------
load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
EXCEL_PATH = os.getenv("EXCEL_PATH")
SHEET_NAME = os.getenv("SHEET_NAME")

database_url = (
    f"postgresql+psycopg://"
    f"{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)
engine = create_engine(database_url)

# --------------------------------------------------
# 2. Hash Helper Function
# --------------------------------------------------
MONITORED_COLUMNS = [
    "order_date",
    "customer_name",
    "customer_region",
    "product_name",
    "category",
    "unit_price",
    "quantity",
    "sales_amount",
]


def build_row_hash(row, columns):
    """Generates a deterministic SHA-256 fingerprint for monitored columns."""
    concatenated = "|".join(str(row[col]).strip().lower() for col in columns)
    return hashlib.sha256(concatenated.encode("utf-8")).hexdigest()


# --------------------------------------------------
# 3. Read & Clean Excel File
# --------------------------------------------------
excel_file = Path(EXCEL_PATH)
incoming = pd.read_excel(excel_file, sheet_name=SHEET_NAME)

# Standardize headers
incoming.columns = (
    incoming.columns.str.strip().str.lower().str.replace(" ", "_")
)

# Standardize data types
incoming["order_date"] = pd.to_datetime(incoming["order_date"]).dt.date
incoming["order_id"] = incoming["order_id"].astype(str).str.strip()
incoming["quantity"] = pd.to_numeric(incoming["quantity"], errors="coerce").fillna(0).astype(int)

for col in ["unit_price", "sales_amount"]:
    if col in incoming.columns:
        incoming[col] = (
            incoming[col]
            .astype(str)
            .str.replace("$", "", regex=False)
            .str.replace("£", "", regex=False)
            .str.replace(",", "", regex=False)
            .str.strip()
        )
        incoming[col] = pd.to_numeric(incoming[col], errors="coerce").fillna(0.0).round(2)

incoming["source_file"] = excel_file.name

# Generate row fingerprint for incoming data
incoming["row_hash"] = incoming.apply(build_row_hash, columns=MONITORED_COLUMNS, axis=1)

# --------------------------------------------------
# 4. Fetch & Hash Existing PostgreSQL Records
# --------------------------------------------------
existing_query = text("""
    SELECT 
        order_id,
        order_date,
        customer_name,
        customer_region,
        product_name,
        category,
        unit_price,
        quantity,
        sales_amount
    FROM raw_sales_tracker
""")

existing = pd.read_sql(existing_query, engine)

if not existing.empty:
    existing["order_id"] = existing["order_id"].astype(str).str.strip()
    existing["order_date"] = pd.to_datetime(existing["order_date"]).dt.date
    existing["quantity"] = pd.to_numeric(existing["quantity"], errors="coerce").fillna(0).astype(int)
    for col in ["unit_price", "sales_amount"]:
        existing[col] = pd.to_numeric(existing[col], errors="coerce").fillna(0.0).round(2)

    existing["row_hash"] = existing.apply(build_row_hash, columns=MONITORED_COLUMNS, axis=1)
    existing_lookup = existing.set_index("order_id")["row_hash"]
else:
    existing_lookup = pd.Series(dtype=str)

# --------------------------------------------------
# 5. Map & Categorize: New vs Changed vs Unchanged
# --------------------------------------------------
incoming["existing_hash"] = incoming["order_id"].map(existing_lookup)

# Case 1: Doesn't exist in DB -> NEW
new_sales = incoming[incoming["existing_hash"].isna()].copy()

# Case 2: Exists, but hash differs -> CHANGED
changed_sales = incoming[
    incoming["existing_hash"].notna()
    & (incoming["row_hash"] != incoming["existing_hash"])
].copy()

# Case 3: Exists and hashes match -> UNCHANGED
unchanged_count = len(incoming) - len(new_sales) - len(changed_sales)

print(f"Rows in Excel:        {len(incoming)}")
print(f"New records:          {len(new_sales)}")
print(f"Changed records:      {len(changed_sales)}")
print(f"Unchanged records:    {unchanged_count}")

# --------------------------------------------------
# 6. Apply Inserts and Updates
# --------------------------------------------------
# Insert new records
if not new_sales.empty:
    cols_to_insert = [c for c in new_sales.columns if c not in ["row_hash", "existing_hash"]]
    new_sales[cols_to_insert].to_sql(
        name="raw_sales_tracker",
        con=engine,
        if_exists="append",
        index=False,
    )
    print(f"{len(new_sales)} new records inserted.")
else:
    print("0 new records inserted.")

# Update changed records
if not changed_sales.empty:
    update_query = text("""
        UPDATE raw_sales_tracker
        SET
            order_date = :order_date,
            customer_name = :customer_name,
            customer_region = :customer_region,
            product_name = :product_name,
            category = :category,
            unit_price = :unit_price,
            quantity = :quantity,
            sales_amount = :sales_amount,
            source_file = :source_file,
            updated_at = CURRENT_TIMESTAMP
        WHERE order_id = :order_id;
    """)

    update_payload = changed_sales.to_dict(orient="records")
    with engine.begin() as conn:
        conn.execute(update_query, update_payload)
    print(f"{len(changed_sales)} existing records updated.")
else:
    print("0 existing records updated.")
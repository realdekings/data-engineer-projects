import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine


# Load configuration from .env
load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

EXCEL_PATH = os.getenv("EXCEL_PATH")
SHEET_NAME = os.getenv("SHEET_NAME")


# Build PostgreSQL connection
database_url = (
    f"postgresql+psycopg://"
    f"{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_engine(database_url)


# Read Excel file
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


# Add source metadata
df["source_file"] = excel_file.name


# Load into PostgreSQL
df.to_sql(
    name="raw_sales_tracker",
    con=engine,
    if_exists="append",
    index=False
)


print(f"{len(df)} rows loaded successfully.")
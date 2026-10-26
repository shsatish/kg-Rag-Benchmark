
from pathlib import Path
import os
import time
import pandas as pd
from openai import OpenAI
from qdrant_client import QdrantClient, models

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

COLLECTION = "retail_rag_benchmark"
EMBED_MODEL = "text-embedding-3-small"
VECTOR_SIZE = 1536
BATCH_SIZE = 100

if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError(
        "OPENAI_API_KEY is missing. Set it in this terminal."
    )

openai_client = OpenAI()
qdrant = QdrantClient(url="http://localhost:6333")

TABLES = [
    "customers", "employees", "inventory_movements",
    "order_items", "orders", "payments", "products",
    "promotions", "returns", "shipments", "stores",
    "suppliers"
]

PRIMARY_KEYS = {
    "customers": "customer_id",
    "employees": "employee_id",
    "inventory_movements": "movement_id",
    "order_items": "order_item_id",
    "orders": "order_id",
    "payments": "payment_id",
    "products": "product_id",
    "promotions": "promotion_id",
    "returns": "return_id",
    "shipments": "shipment_id",
    "stores": "store_id",
    "suppliers": "supplier_id"
}

RELATIONS = {
    "employees": {"store_id": "stores"},
    "products": {"supplier_id": "suppliers"},
    "orders": {
        "customer_id": "customers",
        "store_id": "stores",
        "employee_id": "employees"
    },
    "order_items": {
        "order_id": "orders",
        "product_id": "products",
        "promotion_id": "promotions"
    },
    "payments": {"order_id": "orders"},
    "shipments": {
        "order_id": "orders",
        "store_id": "stores"
    },
    "returns": {
        "order_id": "orders",
        "order_item_id": "order_items",
        "employee_id": "employees"
    },
    "inventory_movements": {
        "product_id": "products",
        "store_id": "stores",
        "order_id": "orders"
    }
}

# Read all source CSV files
data = {
    table: pd.read_csv(
        DATA_DIR / f"{table}.csv",
        dtype=str,
        keep_default_na=False
    )
    for table in TABLES
}

# Lookup related records by their primary key
lookups = {
    table: df.set_index(PRIMARY_KEYS[table]).to_dict("index")
    for table, df in data.items()
}

NAME_FIELDS = {
    "customers": "customer_name",
    "employees": "employee_name",
    "products": "product_name",
    "stores": "store_name",
    "suppliers": "supplier_name",
    "promotions": "campaign_name",
    "orders": "order_number"
}

def build_document(table, row):
    fields = [
        f"Record type: {table}"
    ]

    for column, value in row.items():
        if value:
            fields.append(f"{column}: {value}")

        target_table = RELATIONS.get(table, {}).get(column)

        if target_table and value:
            related = lookups[target_table].get(value, {})
            name_field = NAME_FIELDS.get(target_table)

            if name_field and related.get(name_field):
                fields.append(
                    f"Related {target_table}: "
                    f"{related[name_field]}"
                )

    return ". ".join(fields)

documents = []

for table in TABLES:
    for _, row in data[table].iterrows():
        row_dict = row.to_dict()
        documents.append({
            "table": table,
            "record_id": row_dict[PRIMARY_KEYS[table]],
            "text": build_document(table, row_dict),
            "metadata": row_dict
        })

print(f"Prepared {len(documents)} retail documents")

if qdrant.collection_exists(COLLECTION):
    raise RuntimeError(
        f"Collection '{COLLECTION}' already exists. "
        "Stop to avoid overwriting existing data."
    )

qdrant.create_collection(
    collection_name=COLLECTION,
    vectors_config=models.VectorParams(
        size=VECTOR_SIZE,
        distance=models.Distance.COSINE
    )
)

start_time = time.perf_counter()
embedding_tokens = 0

for start in range(0, len(documents), BATCH_SIZE):
    batch = documents[start:start + BATCH_SIZE]
    texts = [doc["text"] for doc in batch]

    response = openai_client.embeddings.create(
        model=EMBED_MODEL,
        input=texts
    )

    embedding_tokens += response.usage.total_tokens

    points = [
        models.PointStruct(
            id=start + i + 1,
            vector=response.data[i].embedding,
            payload=batch[i]
        )
        for i in range(len(batch))
    ]

    qdrant.upsert(
        collection_name=COLLECTION,
        points=points,
        wait=True
    )

    print(
        f"Uploaded {start + len(batch)}"
        f"/{len(documents)} records"
    )

elapsed = time.perf_counter() - start_time

count = qdrant.count(
    collection_name=COLLECTION,
    exact=True
).count

print("\n===== QDRANT INGESTION COMPLETED =====")
print(f"Documents prepared: {len(documents)}")
print(f"Vectors stored: {count}")
print(f"Embedding tokens: {embedding_tokens:,}")
print(f"Ingestion time: {elapsed:.2f} seconds")

assert count == len(documents)
print("Qdrant validation: PASSED")


from pathlib import Path
import pandas as pd
from rdflib import Graph, Namespace, Literal, RDF, XSD

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
OUTPUT = BASE / "data" / "retail_knowledge_graph.ttl"

EX = Namespace("https://example.org/retail/")
SCHEMA = Namespace("https://schema.org/")

# Dataset name -> primary key
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
    "suppliers": "supplier_id",
}

# Dataset -> foreign-key column -> target dataset
RELATIONSHIPS = {
    "employees": {
        "store_id": "stores"
    },
    "products": {
        "supplier_id": "suppliers"
    },
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
    "payments": {
        "order_id": "orders"
    },
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

g = Graph()
g.bind("retail", EX)
g.bind("schema", SCHEMA)

entity_counts = {}

def entity_uri(table, identifier):
    return EX[f"{table}/{identifier}"]

def make_literal(value, column):
    if column.endswith("_date") or column in [
        "signup_date", "hire_date", "opened_date",
        "start_date", "end_date",
        "promised_delivery_date", "delivered_date"
    ]:
        return Literal(value, datatype=XSD.date)

    if value.lower() in ("true", "false"):
        return Literal(value.lower() == "true")

    if column.endswith("_id"):
        return Literal(value)

    try:
        if "." in value:
            return Literal(value, datatype=XSD.decimal)
        return Literal(int(value), datatype=XSD.integer)
    except ValueError:
        return Literal(value)

for table, primary_key in PRIMARY_KEYS.items():

    file_path = DATA_DIR / f"{table}.csv"
    df = pd.read_csv(file_path, dtype=str, keep_default_na=False)

    print(f"Processing {table}: {len(df)} records")

    entity_counts[table] = len(df)

    for _, row in df.iterrows():

        identifier = str(row[primary_key]).strip()
        subject = entity_uri(table, identifier)

        # Entity type
        g.add((
            subject,
            RDF.type,
            EX[table]
        ))

        for column in df.columns:

            value = str(row[column]).strip()

            if not value:
                continue

            predicate = EX[column]

            # Foreign key -> RDF relationship
            if column in RELATIONSHIPS.get(table, {}):

                target_table = RELATIONSHIPS[table][column]
                target = entity_uri(target_table, value)

                g.add((subject, predicate, target))

            else:
                g.add((
                    subject,
                    predicate,
                    make_literal(value, column)
                ))

print("\nSerializing Knowledge Graph...")

g.serialize(
    destination=str(OUTPUT),
    format="turtle",
    encoding="utf-8"
)

print("\n===== RDF GENERATION COMPLETED =====")
print(f"Output: {OUTPUT}")
print(f"Total source records: {sum(entity_counts.values())}")
print(f"Total RDF triples: {len(g):,}")

# Verify Turtle can be parsed
verify = Graph()
verify.parse(str(OUTPUT), format="turtle")
assert len(verify) == len(g)

print("Turtle validation: PASSED")


import os
import re
import json
import time
import requests
import streamlit as st

from openai import OpenAI
from qdrant_client import QdrantClient


# ============================================================
# CONFIGURATION
# ============================================================

QDRANT_URL = "http://localhost:6333"
QDRANT_COLLECTION = "retail_rag_benchmark"

JENA_ENDPOINT = (
    "http://localhost:3030/Retail-Data-Set/sparql"
)

EMBEDDING_MODEL = "text-embedding-3-small"
LLM_MODEL = "gpt-4o-mini"

MAX_SPARQL_ROWS = 100
MAX_CONTEXT_CHARS = 15000


st.set_page_config(
    page_title="Knowledge Graph vs Vector RAG",
    page_icon="🧠",
    layout="wide"
)


# ============================================================
# CLIENT INITIALIZATION
# ============================================================

if not os.getenv("OPENAI_API_KEY"):
    st.error(
        "OPENAI_API_KEY is missing. "
        "Configure it in your PowerShell session."
    )
    st.stop()

openai_client = OpenAI()
qdrant = QdrantClient(url=QDRANT_URL)


# ============================================================
# RDF SCHEMA
# ============================================================

RDF_SCHEMA = """
The RDF namespace is:
https://example.org/retail/

Required prefixes:

PREFIX retail: <https://example.org/retail/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

Entity classes:

retail:customers
retail:employees
retail:inventory_movements
retail:order_items
retail:orders
retail:payments
retail:products
retail:promotions
retail:returns
retail:shipments
retail:stores
retail:suppliers

Relationships:

products --retail:supplier_id--> suppliers
employees --retail:store_id--> stores

orders --retail:customer_id--> customers
orders --retail:store_id--> stores
orders --retail:employee_id--> employees

order_items --retail:order_id--> orders
order_items --retail:product_id--> products
order_items --retail:promotion_id--> promotions

payments --retail:order_id--> orders

shipments --retail:order_id--> orders
shipments --retail:store_id--> stores

returns --retail:order_id--> orders
returns --retail:order_item_id--> order_items
returns --retail:employee_id--> employees

inventory_movements --retail:product_id--> products
inventory_movements --retail:store_id--> stores
inventory_movements --retail:order_id--> orders

Relevant properties:

retail:product_name
retail:category
retail:brand
retail:supplier_name
retail:supplier_country
retail:customer_name
retail:store_name
retail:city
retail:region
retail:order_date
retail:order_total
retail:quantity
retail:line_amount
retail:unit_price
retail:unit_cost
retail:discount_amount
retail:return_quantity
retail:refund_amount
retail:payment_amount

Important RDF modelling rules:

1. Entity types use rdf:type.

Example:

?product rdf:type retail:products .

2. Foreign keys are RDF URI relationships.

Example:

?product retail:supplier_id ?supplier .

3. Supplier names are literals.

Example:

?supplier retail:supplier_name ?supplierName .

4. Product categories are literals.

Example:

?product retail:category "Electronics" .

5. Do not compare foreign-key relationships
   against string literals.

6. Use the exact class and predicate names
   from this schema.

7. Do not invent properties or relationships.

Example query:

PREFIX retail: <https://example.org/retail/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT DISTINCT ?supplierName
WHERE {
    ?product rdf:type retail:products .
    ?product retail:category "Electronics" .
    ?product retail:supplier_id ?supplier .
    ?supplier retail:supplier_name ?supplierName .
}
ORDER BY ?supplierName
LIMIT 100
"""


# ============================================================
# VECTOR RAG
# ============================================================

def ask_vector(question, top_k):

    total_start = time.perf_counter()

    # --------------------------------------------------------
    # STEP 1: QUESTION EMBEDDING
    # --------------------------------------------------------

    embedding_start = time.perf_counter()

    embedding_response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=question
    )

    query_vector = embedding_response.data[0].embedding
    embedding_tokens = embedding_response.usage.total_tokens

    embedding_time = (
        time.perf_counter() - embedding_start
    )

    # --------------------------------------------------------
    # STEP 2: QDRANT SEARCH
    # --------------------------------------------------------

    retrieval_start = time.perf_counter()

    search_result = qdrant.query_points(
        collection_name=QDRANT_COLLECTION,
        query=query_vector,
        limit=top_k,
        with_payload=True
    )

    retrieval_time = (
        time.perf_counter() - retrieval_start
    )

    sources = []

    for index, point in enumerate(
        search_result.points, start=1
    ):

        payload = point.payload or {}

        sources.append({
            "source": index,
            "table": payload.get("table", ""),
            "record_id": payload.get("record_id", ""),
            "score": point.score,
            "text": payload.get("text", "")
        })

    context = "\n\n".join(
        f"[{item['source']}] {item['text']}"
        for item in sources
    )

    # --------------------------------------------------------
    # STEP 3: OPENAI ANSWER
    # --------------------------------------------------------

    llm_start = time.perf_counter()

    response = openai_client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a retail business analyst. "
                    "Answer only from retrieved records. "
                    "Do not invent facts. "
                    "If evidence is insufficient, say so. "
                    "Reference source numbers where possible."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\n"
                    f"Retrieved evidence:\n{context}"
                )
            }
        ]
    )

    llm_time = time.perf_counter() - llm_start

    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens

    return {
        "answer": response.choices[0].message.content,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "embedding_tokens": embedding_tokens,
        "total_tokens": (
            input_tokens + output_tokens + embedding_tokens
        ),
        "preparation_time": embedding_time,
        "retrieval_time": retrieval_time,
        "generation_time": llm_time,
        "total_time": time.perf_counter() - total_start,
        "sources": sources,
        "query": None
    }


# ============================================================
# SPARQL QUERY CLEANING AND VALIDATION
# ============================================================

def prepare_sparql(raw_query):

    query = raw_query.strip()

    # Remove Markdown code fences.
    query = re.sub(
        r"^```(?:sparql)?\s*",
        "",
        query,
        flags=re.IGNORECASE
    )

    query = re.sub(
        r"\s*```$",
        "",
        query
    ).strip()

    # Remove a trailing semicolon, if present.
    query = query.rstrip("; \r\n\t")

    # Basic read-only validation.
    # This is not a production security boundary.
    forbidden = re.search(
        r"\b(INSERT|DELETE|DROP|CLEAR|LOAD|CREATE|"
        r"MOVE|COPY|ADD|SERVICE|CONSTRUCT|DESCRIBE|"
        r"ASK|UPDATE)\b",
        query,
        flags=re.IGNORECASE
    )

    if forbidden:
        raise ValueError(
            "Generated query contains an unsupported operation."
        )

    if not re.search(
        r"\bSELECT\b",
        query,
        flags=re.IGNORECASE
    ):
        raise ValueError(
            "Generated SPARQL must be a SELECT query."
        )

    # If no limit exists, add one.
    if not re.search(
        r"\bLIMIT\s+\d+\b",
        query,
        flags=re.IGNORECASE
    ):
        query += f"\nLIMIT {MAX_SPARQL_ROWS}"

    return query


# ============================================================
# KNOWLEDGE GRAPH RAG
# ============================================================

def ask_knowledge_graph(question):

    total_start = time.perf_counter()

    # --------------------------------------------------------
    # STEP 1: GENERATE SPARQL
    # --------------------------------------------------------

    query_start = time.perf_counter()

    query_response = openai_client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert Apache Jena SPARQL developer.\n"
                    "Generate one syntactically valid SPARQL SELECT query.\n"
                    "Return only executable SPARQL text.\n"
                    "Do not include Markdown or explanations.\n"
                    "Use the supplied RDF schema exactly.\n"
                    "Use proper RDF URI joins.\n"
                    "Use DISTINCT where appropriate.\n"
                    "Limit ordinary result sets to 100 rows.\n\n"
                    + RDF_SCHEMA
                )
            },
            {
                "role": "user",
                "content": question
            }
        ]
    )

    query_time = time.perf_counter() - query_start

    raw_sparql = (
        query_response.choices[0].message.content or ""
    )

    sparql = prepare_sparql(raw_sparql)

    query_input_tokens = query_response.usage.prompt_tokens
    query_output_tokens = query_response.usage.completion_tokens

    # --------------------------------------------------------
    # STEP 2: EXECUTE SPARQL IN APACHE JENA
    # --------------------------------------------------------

    retrieval_start = time.perf_counter()

    try:
        jena_response = requests.post(
            JENA_ENDPOINT,
            data={"query": sparql},
            headers={
                "Accept": "application/sparql-results+json"
            },
            timeout=60
        )

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Cannot connect to Apache Jena: {exc}"
        ) from exc

    retrieval_time = (
        time.perf_counter() - retrieval_start
    )

    # --------------------------------------------------------
    # IMPORTANT: DISPLAY THE REAL JENA ERROR
    # --------------------------------------------------------

    if not jena_response.ok:

        st.error(
            f"Apache Jena returned HTTP "
            f"{jena_response.status_code}"
        )

        st.subheader("Generated SPARQL")
        st.code(sparql, language="sparql")

        st.subheader("Apache Jena Error Details")
        st.code(jena_response.text)

        st.subheader("Failed Query Token Consumption")

        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Input Tokens",
            query_input_tokens
        )

        c2.metric(
            "Output Tokens",
            query_output_tokens
        )

        c3.metric(
            "Total Tokens",
            query_input_tokens + query_output_tokens
        )

        st.caption(
            f"SPARQL generation: {query_time:.3f}s | "
            f"Jena request: {retrieval_time:.3f}s"
        )

        raise ValueError(
            "SPARQL execution failed. "
            "Review the generated query and Jena error above."
        )

    # --------------------------------------------------------
    # STEP 3: PARSE JENA RESULTS
    # --------------------------------------------------------

    data = jena_response.json()

    variables = data["head"]["vars"]
    bindings = data["results"]["bindings"]

    rows = []

    for binding in bindings:

        row = {}

        for variable in variables:

            value = binding.get(variable, {})
            row[variable] = value.get("value", "")

        rows.append(row)

    context = json.dumps(
        rows,
        ensure_ascii=False
    )[:MAX_CONTEXT_CHARS]

    # --------------------------------------------------------
    # STEP 4: OPENAI ANSWER
    # --------------------------------------------------------

    answer_start = time.perf_counter()

    answer_response = openai_client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a retail business analyst. "
                    "Answer using only the SPARQL results. "
                    "Do not invent facts. "
                    "If results are incomplete, state that. "
                    "Give a clear and concise business answer."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\n"
                    f"SPARQL results:\n{context}"
                )
            }
        ]
    )

    answer_time = (
        time.perf_counter() - answer_start
    )

    answer_input_tokens = answer_response.usage.prompt_tokens
    answer_output_tokens = answer_response.usage.completion_tokens

    total_input = query_input_tokens + answer_input_tokens
    total_output = query_output_tokens + answer_output_tokens

    return {
        "answer": answer_response.choices[0].message.content,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "query_tokens": (
            query_input_tokens + query_output_tokens
        ),
        "total_tokens": total_input + total_output,
        "preparation_time": query_time,
        "retrieval_time": retrieval_time,
        "generation_time": answer_time,
        "total_time": time.perf_counter() - total_start,
        "sources": rows,
        "query": sparql
    }


# ============================================================
# STREAMLIT USER INTERFACE
# ============================================================

st.title("🧠 Knowledge Graph vs Vector RAG")

st.markdown(
    "### Retail Data Intelligence — Performance & Token Benchmark"
)

st.info(
    "Both retrieval approaches use the same retail source "
    "datasets and OpenAI answer-generation model."
)

with st.sidebar:

    st.header("Benchmark Configuration")

    st.write("**LLM:**", LLM_MODEL)
    st.write("**Embedding Model:**", EMBEDDING_MODEL)
    st.write("**Vector Database:** Qdrant")
    st.write("**Graph Database:** Apache Jena Fuseki")

    top_k = st.slider(
        "Vector Retrieval Top-K",
        min_value=3,
        max_value=50,
        value=50
    )

question = st.text_area(
    "Enter your retail business question",
    value="Which suppliers provide electronics products?",
    height=100
)

col1, col2 = st.columns(2)

with col1:
    vector_button = st.button(
        "🔍 Ask Vector",
        use_container_width=True
    )

with col2:
    graph_button = st.button(
        "🕸️ Ask Knowledge Graph",
        use_container_width=True
    )


# ============================================================
# SESSION STATE
# ============================================================

if "vector_result" not in st.session_state:
    st.session_state.vector_result = None

if "graph_result" not in st.session_state:
    st.session_state.graph_result = None

if "last_question" not in st.session_state:
    st.session_state.last_question = question

if "last_top_k" not in st.session_state:
    st.session_state.last_top_k = top_k

if st.session_state.last_question != question:

    st.session_state.vector_result = None
    st.session_state.graph_result = None
    st.session_state.last_question = question

if st.session_state.last_top_k != top_k:

    st.session_state.vector_result = None
    st.session_state.last_top_k = top_k


# ============================================================
# EXECUTE REQUESTS
# ============================================================

if vector_button:

    if question.strip():

        try:
            with st.spinner("Executing Vector RAG..."):

                st.session_state.vector_result = ask_vector(
                    question,
                    top_k
                )

        except Exception as exc:
            st.session_state.vector_result = None
            st.error(f"Vector RAG failed: {exc}")

    else:
        st.warning("Please enter a business question.")


if graph_button:

    if question.strip():

        try:
            with st.spinner(
                "Generating SPARQL and querying Apache Jena..."
            ):

                st.session_state.graph_result = (
                    ask_knowledge_graph(question)
                )

        except Exception as exc:
            st.session_state.graph_result = None
            st.error(f"Knowledge Graph RAG failed: {exc}")

    else:
        st.warning("Please enter a business question.")


# ============================================================
# DISPLAY RESULTS
# ============================================================

def display_result(result, mode):

    if result is None:

        st.info(f"Run {mode} to view the result.")
        return

    st.markdown("#### Answer")
    st.write(result["answer"])

    st.markdown("#### Token Consumption")

    st.metric(
        "Total API Tokens",
        f'{result["total_tokens"]:,}'
    )

    a, b = st.columns(2)

    a.metric(
        "Input Tokens",
        f'{result["input_tokens"]:,}'
    )

    b.metric(
        "Output Tokens",
        f'{result["output_tokens"]:,}'
    )

    if mode == "Vector RAG":

        st.caption(
            f"Additional query embedding tokens: "
            f"{result['embedding_tokens']}"
        )

    else:

        st.caption(
            f"SPARQL generation tokens: "
            f"{result['query_tokens']} "
            "(already included in total)"
        )

    st.markdown("#### Performance")

    a, b = st.columns(2)
    c, d = st.columns(2)

    a.metric(
        "Preparation",
        f'{result["preparation_time"]:.3f}s'
    )

    b.metric(
        "Retrieval",
        f'{result["retrieval_time"]:.3f}s'
    )

    c.metric(
        "Answer Generation",
        f'{result["generation_time"]:.3f}s'
    )

    d.metric(
        "End-to-End",
        f'{result["total_time"]:.3f}s'
    )

    if result["query"]:

        with st.expander("View Generated SPARQL"):
            st.code(
                result["query"],
                language="sparql"
            )

    with st.expander("View Retrieved Evidence"):

        if mode == "Knowledge Graph RAG":
            st.dataframe(result["sources"])
        else:
            st.write(result["sources"])


st.divider()

left, right = st.columns(2)

with left:

    st.subheader("🔍 Vector RAG")

    display_result(
        st.session_state.vector_result,
        "Vector RAG"
    )

with right:

    st.subheader("🕸️ Knowledge Graph RAG")

    display_result(
        st.session_state.graph_result,
        "Knowledge Graph RAG"
    )


# ============================================================
# SIDE-BY-SIDE COMPARISON
# ============================================================

vector_result = st.session_state.vector_result
graph_result = st.session_state.graph_result

if vector_result and graph_result:

    st.divider()

    st.subheader("📊 Performance Comparison")

    comparison = [
        {
            "Metric": "Total API Tokens",
            "Vector RAG": vector_result["total_tokens"],
            "Knowledge Graph RAG": graph_result["total_tokens"]
        },
        {
            "Metric": "Input Tokens",
            "Vector RAG": vector_result["input_tokens"],
            "Knowledge Graph RAG": graph_result["input_tokens"]
        },
        {
            "Metric": "Output Tokens",
            "Vector RAG": vector_result["output_tokens"],
            "Knowledge Graph RAG": graph_result["output_tokens"]
        },
        {
            "Metric": "Preparation Time (s)",
            "Vector RAG": round(
                vector_result["preparation_time"], 3
            ),
            "Knowledge Graph RAG": round(
                graph_result["preparation_time"], 3
            )
        },
        {
            "Metric": "Retrieval Time (s)",
            "Vector RAG": round(
                vector_result["retrieval_time"], 3
            ),
            "Knowledge Graph RAG": round(
                graph_result["retrieval_time"], 3
            )
        },
        {
            "Metric": "Answer Generation (s)",
            "Vector RAG": round(
                vector_result["generation_time"], 3
            ),
            "Knowledge Graph RAG": round(
                graph_result["generation_time"], 3
            )
        },
        {
            "Metric": "End-to-End Time (s)",
            "Vector RAG": round(
                vector_result["total_time"], 3
            ),
            "Knowledge Graph RAG": round(
                graph_result["total_time"], 3
            )
        }
    ]

    st.dataframe(
        comparison,
        use_container_width=True,
        hide_index=True
    )

    vector_tokens = vector_result["total_tokens"]
    graph_tokens = graph_result["total_tokens"]

    if vector_tokens > 0:

        reduction = (
            (vector_tokens - graph_tokens)
            / vector_tokens
        ) * 100

        st.metric(
            "Knowledge Graph Token Reduction",
            f"{reduction:.1f}%"
        )

        if reduction < 0:
            st.warning(
                "Knowledge Graph RAG consumed more tokens "
                "than Vector RAG for this question."
            )
        else:
            st.success(
                "Knowledge Graph RAG consumed fewer tokens "
                "for this question."
            )

    st.caption(
        "Results are from individual executions. "
        "Both answer accuracy and repeated-run performance "
        "must be assessed before drawing conclusions."
    )

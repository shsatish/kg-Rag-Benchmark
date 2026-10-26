# KG RAG Benchmark — Installation & Local Setup

This repository contains a local retail RAG demo using **Apache Jena Fuseki**, **Qdrant**, **Python** and **Streamlit**. This README is an **installation and execution guide only**. Benchmark methodology, results, interpretation and the ASC model will be described in the accompanying Medium article.

## Repository structure

```text
kg-Rag-Benchmark/
├── app/                 # Streamlit comparison application
├── data/                # Retail CSV input files
├── rdf-atlas-jena/      # Apache Jena Docker Compose configuration
├── scripts/             # RDF generation and Qdrant ingestion
└── README.md
```

> The repository screenshot confirms the folder names but not every nested filename. Check `app/` and `scripts/` before executing commands; replace the example filename if yours differs.

## 1. Prerequisites

Install:

- [Git](https://git-scm.com/downloads)
- [Python 3.11](https://www.python.org/downloads/) with `pip`
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) with the Linux engine running
- [VS Code](https://code.visualstudio.com/) or another editor
- An [OpenAI API key](https://platform.openai.com/api-keys) with available credits

The example commands below are for **Windows PowerShell**. The original setup used `docker-compose`; some Docker installations use `docker compose` (with a space).

Check prerequisites:

```powershell
git --version
py -3.11 --version
docker info
docker-compose version
```

## 2. Clone the repository

```powershell
git clone https://github.com/shsatish/kg-Rag-Benchmark.git
cd kg-Rag-Benchmark
```

If the repository address differs, copy its HTTPS URL using GitHub's **Code** button.

Inspect the available files:

```powershell
Get-ChildItem
Get-ChildItem .\scripts
Get-ChildItem .\app
Get-ChildItem .\rdf-atlas-jena
```

## 3. Set up Python

Create a project-local virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

If the repository contains `requirements.txt`, install it:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Otherwise, install the required libraries:

```powershell
.\.venv\Scripts\python.exe -m pip install pandas rdflib requests openai qdrant-client streamlit python-dotenv
```

Verify the environment:

```powershell
.\.venv\Scripts\python.exe -c "import pandas, rdflib, openai, qdrant_client, streamlit; print('Dependencies OK')"
```

Always run the scripts with `.\.venv\Scripts\python.exe`, so packages are imported from the same Python environment into which they were installed.

## 4. Configure your own OpenAI API key

**Each user must supply their own OpenAI API key. No key is included in this public repository.**

Create a key at <https://platform.openai.com/api-keys> and set it in the PowerShell terminal that will run the ingestion scripts and Streamlit:

```powershell
$env:OPENAI_API_KEY = "YOUR_OWN_OPENAI_API_KEY"
```

Confirm it is configured without displaying the secret:

```powershell
if ($env:OPENAI_API_KEY) { "API key configured" } else { "API key missing" }
```

The variable persists only for that PowerShell session. Set it again in any new terminal, or use a local `.env` file if your scripts load it with `python-dotenv`.

Optional `.env` example:

```dotenv
OPENAI_API_KEY=replace_with_your_own_key
```

**Never commit `.env` or API keys to GitHub.** Recommended `.gitignore` entries:

```gitignore
.env
.env.*
!.env.example
.venv/
__pycache__/
*.pyc
qdrant_storage/
fuseki_data/
```

## 5. Start Apache Jena Fuseki

Ensure Docker Desktop is running. From the repository root:

```powershell
cd .\rdf-atlas-jena
docker-compose up -d fuseki
docker-compose ps
docker-compose logs --tail=50 fuseki
```

The original project used a Docker Compose `fuseki` service on **port 3030**, with a persistent Docker volume. If the repository also contains the optional explorer application and you want it, start/build the full Compose project:

```powershell
docker-compose up -d --build
```

Open **http://localhost:3030**. In the Fuseki interface, create a persistent dataset named:

```text
Retail-Data-Set
```

The SPARQL endpoint will be:

```text
http://localhost:3030/Retail-Data-Set/sparql
```

If the Python application references another dataset name or query URL, update its configuration to match. For a first run, make sure the dataset is empty before uploading RDF.

Return to the repository root:

```powershell
cd ..
```

## 6. Generate and upload RDF (.ttl)

Inspect the provided scripts to identify the **CSV-to-Turtle generator**:

```powershell
Get-ChildItem .\scripts\*.py
Get-ChildItem .\data\*.csv
```

Run the generator using its **actual repository filename**:

```powershell
.\.venv\Scripts\python.exe .\scripts\YOUR_CSV_TO_TTL_SCRIPT.py
```

Replace `YOUR_CSV_TO_TTL_SCRIPT.py` with the filename present under `scripts/`. Check the script or terminal output for the resulting `.ttl` path. The original experiment used a file named `retail_knowledge_graph.ttl`.

Upload the Turtle file:

1. Open **http://localhost:3030**.
2. Open the **Retail-Data-Set** dataset.
3. Select **Add data**.
4. Select the generated `.ttl` file and upload it to the default graph.
5. Open **Query** and verify that data exists:

```sparql
SELECT (COUNT(*) AS ?totalTriples)
WHERE { ?s ?p ?o . }
```

For the original sample dataset, the expected count after upload was **52,394 triples**. Repeated uploads should be avoided unless you intentionally want to refresh the dataset.

## 7. Start Qdrant using Docker

Open PowerShell and start Qdrant with a persistent named volume:

```powershell
docker pull qdrant/qdrant
docker volume create qdrant_storage
docker run -d --name qdrant -p 127.0.0.1:6333:6333 -p 127.0.0.1:6334:6334 -v qdrant_storage:/qdrant/storage qdrant/qdrant
```

If the container already exists but has stopped, run:

```powershell
docker start qdrant
```

Verify:

```powershell
docker ps
Invoke-RestMethod -Uri "http://localhost:6333/collections" -Method GET
```

Open the Qdrant dashboard at **http://localhost:6333/dashboard**.

## 8. Ingest retail records into Qdrant

From the repository root, with `OPENAI_API_KEY` set in the current terminal:

```powershell
.\.venv\Scripts\python.exe .\scripts\ingest_qdrant.py
```

The original demo used the following configuration (verify against the uploaded script):

| Setting | Original value |
|---|---|
| Qdrant URL | `http://localhost:6333` |
| Collection | `retail_rag_benchmark` |
| Embedding model | `text-embedding-3-small` |
| Vector dimension | `1536` |
| Distance | Cosine |
| Sample collection size | 5,360 points |

Check the collection:

```powershell
Invoke-RestMethod -Uri "http://localhost:6333/collections/retail_rag_benchmark" -Method GET
```

**Note:** Embedding ingestion makes billable OpenAI API calls. If you have already ingested the data, avoid re-running the ingestion script without first checking how it handles existing points.

## 9. Run the Streamlit application

List the app files:

```powershell
Get-ChildItem .\app\*.py
```

If the main Streamlit file is called `app.py`, launch it with:

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\app\app.py
```

Otherwise, replace `app.py` with the actual application filename.

Open **http://localhost:8501**. You should be able to select **Ask Vector** or **Ask Knowledge Graph** and submit a natural-language question. Ensure the application points to the Jena dataset and Qdrant collection configured above.

## 10. Quick service checklist

| Check | Address / command |
|---|---|
| Docker running | `docker ps` |
| Fuseki UI | http://localhost:3030 |
| Fuseki dataset | `Retail-Data-Set` |
| Fuseki SPARQL endpoint | http://localhost:3030/Retail-Data-Set/sparql |
| Qdrant dashboard | http://localhost:6333/dashboard |
| Qdrant collection | `retail_rag_benchmark` |
| Streamlit application | http://localhost:8501 |

## 11. Common troubleshooting

| Error | Resolution |
|---|---|
| `docker` cannot connect | Start Docker Desktop and check `docker info`. |
| `docker-compose` unavailable | Try `docker compose` instead. |
| Port 3030 or 6333 unavailable | Check existing containers and processes using those ports. |
| Jena dataset not found | Create `Retail-Data-Set` or update the app's configured URL. |
| SPARQL query returns no data | Verify `.ttl` upload and dataset selection. |
| Qdrant collection not found | Complete Qdrant ingestion; verify collection name. |
| Vector dimension mismatch | Use the embedding model/dimension expected by the collection. |
| `ModuleNotFoundError: pandas` | Install into `.venv` and execute with `.venv\Scripts\python.exe`. |
| OpenAI authentication error | Configure your own API key in the current terminal. |
| OpenAI SDK import error | Use a clean Python 3.11 environment with compatible dependencies. |
| Slow package downloads | Retry `pip install` using `--default-timeout 180 --retries 10`. |

## Stop and restart local services

Stop or restart Fuseki from `rdf-atlas-jena/`:

```powershell
cd .\rdf-atlas-jena
docker-compose stop
docker-compose up -d fuseki
cd ..
```

Stop or restart Qdrant:

```powershell
docker stop qdrant
docker start qdrant
```

Docker named volumes preserve the stored data when containers are stopped. **Do not delete volumes** unless you intentionally want to remove the ingested data.

---

**Next:** Open the Streamlit app and test both retrieval options. For the experimental design, benchmark numbers, screenshots, and mathematical ASC selection framework, see the accompanying **Medium article** (link to be added after publication).



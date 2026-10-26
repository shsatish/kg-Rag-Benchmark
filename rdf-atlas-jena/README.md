# RDF Atlas — Apache Jena Knowledge Graph Explorer

A Neo4j-style browser for RDF triples. Fuseki stores the data; a small read-only HTTP bridge queries SPARQL and a Cytoscape.js canvas visualizes it.

## Run

1. Set `FUSEKI_ADMIN_PASSWORD` to a unique password, for example in a local `.env` file. Do not expose either port publicly without authentication and HTTPS.
2. Run `docker compose up -d --build` (or `docker-compose up -d --build` on installations like yours).
3. Open <http://localhost:3030>, log in to Fuseki, create a **persistent** TDB2 dataset named `kg`, and upload your `.ttl`, `.nt`, `.rdf`, or `.trig` RDF files.
4. Open <http://localhost:8080> and select **Load graph**. Search for entities, click nodes to inspect properties, and double-click nodes to expand neighbors.

Set `FUSEKI_DATASET` to an existing dataset name if it is not `kg`.

## Connecting an existing Fuseki deployment

If Fuseki is already running in Docker Compose, **do not start a second copy**. Copy the `explorer` service into your current Compose file, set `FUSEKI_QUERY_URL` to `http://YOUR_FUSEKI_SERVICE:3030/YOUR_DATASET/query`, ensure the containers share a Docker network, and remove the explorer service's `depends_on` if your existing service has a different name.

## Features and limitations

- Zoom, drag, fit, and organize graph nodes.
- Search by IRI or literal content (substring queries may be slow on very large datasets).
- Inspect outgoing RDF predicates and literal values.
- Expand incoming/outgoing IRI relationships.
- Show 10–300 triples per request, not a truncation of the underlying graph.

Blank nodes and literal objects do not appear as standalone canvas nodes in this first version; literal properties appear in the inspector. Named graphs may require a union default graph or modified SPARQL query. The browser loads Cytoscape.js from a CDN and therefore needs internet access unless that library is vendored locally.

## Security

The sample binds both ports to `127.0.0.1`. The viewer has no login; use an authenticated reverse proxy before sharing. It only sends read-only SELECT queries to a fixed server-side endpoint. `stain/jena-fuseki` is a community-maintained image, not an Apache Software Foundation release: review and pin a digest for production use.

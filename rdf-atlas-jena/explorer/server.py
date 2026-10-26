import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ENDPOINT = os.environ.get("FUSEKI_QUERY_URL", "http://fuseki:3030/kg/query")
IRI = re.compile(r"^https?://[^<>\s\"{}|^`\\]+$|^urn:[^<>\s\"{}|^`\\]+$")


def numeric(raw, default=30, maximum=300):
    try:
        return max(1, min(int(raw), maximum))
    except (TypeError, ValueError):
        return default


def sparql(query):
    req = Request(ENDPOINT, data=query.encode("utf-8"), headers={
        "Content-Type": "application/sparql-query; charset=utf-8",
        "Accept": "application/sparql-results+json",
    })
    with urlopen(req, timeout=20) as response:
        return json.load(response)["results"]["bindings"]


def compact(uri):
    return uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1] or uri


def graph(bindings, center=None):
    nodes, edges = {}, {}
    for row in bindings:
        s, p, o = (row[k] for k in ("s", "p", "o"))
        sid = s["value"]
        nodes[sid] = {"data": {"id": sid, "label": compact(sid), "kind": "resource"}}
        if o["type"] in ("uri", "bnode"):
            oid = o["value"]
            nodes[oid] = {"data": {"id": oid, "label": compact(oid), "kind": "resource"}}
            eid = json.dumps([sid, p["value"], oid])
            edges[eid] = {"data": {"id": eid, "source": sid, "target": oid,
                                   "label": compact(p["value"]), "predicate": p["value"]}}
    return {"nodes": list(nodes.values()), "edges": list(edges.values()), "center": center}


class Handler(BaseHTTPRequestHandler):
    def respond(self, code, data):
        payload = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path in ("/", "/index.html"):
            with open("/app/index.html", "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        args = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        limit = numeric(args.get("limit"))
        uri = args.get("uri", "")
        try:
            if parsed.path == "/api/overview":
                q = f"SELECT ?s ?p ?o WHERE {{ ?s ?p ?o . FILTER(isIRI(?s) && isIRI(?o)) }} LIMIT {limit}"
                self.respond(200, graph(sparql(q)))
            elif parsed.path == "/api/expand":
                if not IRI.fullmatch(uri):
                    return self.respond(400, {"error": "Enter a valid http(s) or urn IRI"})
                q = f"SELECT ?s ?p ?o WHERE {{ {{ BIND(<{uri}> AS ?s) ?s ?p ?o }} UNION {{ ?s ?p <{uri}> . BIND(<{uri}> AS ?o) }} FILTER(isIRI(?s) && isIRI(?o)) }} LIMIT {limit}"
                self.respond(200, graph(sparql(q), uri))
            elif parsed.path == "/api/properties":
                if not IRI.fullmatch(uri):
                    return self.respond(400, {"error": "Enter a valid IRI"})
                q = f"SELECT ?p ?o WHERE {{ <{uri}> ?p ?o }} LIMIT 200"
                properties = [{"predicate": x["p"]["value"], "value": x["o"]["value"],
                               "type": x["o"]["type"], "lang": x["o"].get("xml:lang", "")}
                              for x in sparql(q)]
                self.respond(200, {"uri": uri, "properties": properties})
            elif parsed.path == "/api/search":
                term = args.get("q", "").strip()
                if not term or len(term) > 120:
                    return self.respond(400, {"error": "Search text must contain 1–120 characters"})
                literal = json.dumps(term, ensure_ascii=False)
                q = f"SELECT DISTINCT ?s WHERE {{ ?s ?p ?o . FILTER(isIRI(?s) && (CONTAINS(LCASE(STR(?s)), LCASE({literal})) || (isLiteral(?o) && CONTAINS(LCASE(STR(?o)), LCASE({literal}))))) }} LIMIT {limit}"
                self.respond(200, {"results": [{"uri": r["s"]["value"], "label": compact(r["s"]["value"])} for r in sparql(q)]})
            else:
                self.respond(404, {"error": "Not found"})
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
            self.respond(502, {"error": "Fuseki query failed. Confirm the dataset and endpoint exist.", "detail": str(exc)[:250]})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()

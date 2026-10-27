#!/usr/bin/env python3
"""Mock AI Service for the seekdb AI function test suite.

It answers the request protocols the seekdb AI functions use:

  OpenAI embeddings   POST /v1/embeddings          -> {"data": [{"index": i, "embedding": [...]}]}
  OpenAI chat         POST /v1/chat/completions    -> {"choices": [{"message": {"role": "assistant", "content": "..."}}]}
  OpenAI rerank       POST /v1/rerank              -> {"results": [{"index": i, "relevance_score": s}]}
  Ollama embeddings   POST /api/embeddings         -> {"embeddings": [[...], ...]}
  Ollama generate     POST /api/generate           -> {"response": "...", "done": true}

The behaviour is driven by the request itself, no model name is special
cased.  The following members of an embedding request steer the answer:

  dimensions   the length of the returned vectors
  inputs       a list of strings, one vector is returned per input
  input        a single string

The service can be told to misbehave so that the error paths of the AI
functions can be exercised:

  X-Mock-Fail: <status>     the service answers with that http status code
  X-Mock-Bad-Dimension: 1   the service answers with a wrong vector length
  X-Mock-Empty: 1           the service answers with an empty completion
  X-Mock-Shuffle: 1         the service answers the embeddings out of order
  X-Mock-Null: 1            the service answers one embedding as null

Usage:
    python3 mock_ai_service.py [--port 8000] [--host 0.0.0.0] [--dimension 8]
"""

import argparse
import json
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def deterministic_vector(text, dimension, seed=0):
    """Return a stable vector for a text so that a rerun gives the same answer."""
    rng = random.Random((hash(text) & 0xFFFFFFFF) ^ (seed * 2654435761 & 0xFFFFFFFF))
    return [round(rng.uniform(-1.0, 1.0), 6) for _ in range(dimension)]


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MockAIService/1.0"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def log_message(self, fmt, *args):
        if self.server.verbose:
            print("[mock-ai] " + (fmt % args), flush=True)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _header_flag(self, name):
        return self.headers.get(name, "") not in ("", "0", "false")

    def _requested_dimension(self, body, default):
        dimension = body.get("dimensions")
        if isinstance(dimension, bool) or not isinstance(dimension, int):
            return default
        if dimension <= 0:
            return default
        return dimension

    @staticmethod
    def _input_list(body):
        """Return the list of inputs of an embedding request."""
        if "input" in body:
            value = body["input"]
            if isinstance(value, list):
                return [item if isinstance(item, str) else json.dumps(item)
                        for item in value]
            if isinstance(value, str):
                return [value]
            return [json.dumps(value)]
        if "inputs" in body:
            value = body["inputs"]
            if isinstance(value, list):
                return [item if isinstance(item, str) else json.dumps(item)
                        for item in value]
            if isinstance(value, str):
                return [value]
        return []

    # ------------------------------------------------------------------
    # request handling
    # ------------------------------------------------------------------
    def do_POST(self):
        body = self._read_json()
        path = self.path.split("?")[0].rstrip("/")

        fail_status = self.headers.get("X-Mock-Fail")
        if fail_status:
            try:
                self._send_json({"error": {"message": "mock failure"}},
                                int(fail_status))
            except ValueError:
                self._send_json({"error": {"message": "mock failure"}}, 500)
            return

        if path.endswith("/embeddings"):
            self._handle_embeddings(body)
        elif path.endswith("/chat/completions"):
            self._handle_chat(body)
        elif path.endswith("/generate"):
            self._handle_ollama_generate(body)
        elif path.endswith("/rerank"):
            self._handle_rerank(body)
        else:
            self._send_json({"error": {"message": "unknown endpoint " + path}}, 404)

    # ------------------------------------------------------------------
    # protocol handlers
    # ------------------------------------------------------------------
    def _handle_embeddings(self, body):
        """OpenAI style embeddings, the answer carries the index of every input."""
        dimension = self._requested_dimension(body, self.server.default_dimension)
        inputs = self._input_list(body)
        if not inputs:
            self._send_json({"error": {"message": "no input"}}, 400)
            return

        if self._header_flag("X-Mock-Bad-Dimension"):
            dimension = dimension + 1

        embeddings = [deterministic_vector(text, dimension)
                      for text in inputs]

        if self._header_flag("X-Mock-Null") and embeddings:
            embeddings[0] = None

        data = [{"object": "embedding", "index": i, "embedding": vec}
                for i, vec in enumerate(embeddings)]

        if self._header_flag("X-Mock-Shuffle"):
            # The service answers out of order, the index tells the caller
            # which input every embedding belongs to.
            shuffled = list(data)
            random.Random(1234).shuffle(shuffled)
            data = shuffled

        self._send_json({"object": "list", "data": data,
                         "model": body.get("model", "")})

    def _handle_chat(self, body):
        """OpenAI style chat completion."""
        messages = body.get("messages") or []
        prompt = ""
        for message in reversed(messages):
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                prompt = message["content"]
                break

        if self._header_flag("X-Mock-Empty"):
            content = ""
        else:
            content = "mock completion for: " + prompt

        self._send_json({
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "model": body.get("model", ""),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": len(prompt), "completion_tokens": len(content),
                      "total_tokens": len(prompt) + len(content)},
        })

    def _handle_ollama_generate(self, body):
        """Ollama native generate protocol."""
        prompt = body.get("prompt")
        if not isinstance(prompt, str):
            prompt = ""
        if self._header_flag("X-Mock-Empty"):
            content = ""
        else:
            content = "mock ollama response for: " + prompt
        self._send_json({
            "model": body.get("model", ""),
            "response": content,
            "done": True,
        })

    def _handle_rerank(self, body):
        """OpenAI / SiliconFlow style rerank."""
        query = body.get("query") or ""
        documents = body.get("documents") or []
        results = []
        for i, document in enumerate(documents):
            text = document if isinstance(document, str) else json.dumps(document)
            score = deterministic_vector(text + str(query), 1)[0]
            results.append({"index": i, "relevance_score": score})

        top_n = body.get("top_n")
        if isinstance(top_n, int) and top_n > 0:
            results = results[:top_n]

        self._send_json({"id": "rerank-mock", "model": body.get("model", ""),
                         "results": results})


class MockAIServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, default_dimension, verbose):
        super().__init__(address, handler)
        self.default_dimension = default_dimension
        self.verbose = verbose


def main():
    parser = argparse.ArgumentParser(description="Mock AI Service for seekdb tests")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dimension", type=int, default=8,
                        help="default length of the returned embedding vectors")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    server = MockAIServer((args.host, args.port), MockHandler,
                           args.dimension, args.verbose)
    print("[mock-ai] listening on %s:%d, default dimension %d"
          % (args.host, args.port, args.dimension), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

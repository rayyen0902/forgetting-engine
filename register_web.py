"""Tiny web server — user-facing registration page. Stdlib only, no frameworks."""

import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from billing import TenantStore

PAGE = """<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>遗忘引擎 - 注册</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,sans-serif;background:#f5f5f5;display:flex;justify-content:center;align-items:center;min-height:100vh}
.card{background:#fff;border-radius:12px;padding:40px;max-width:420px;width:100%;box-shadow:0 2px 12px rgba(0,0,0,.08)}
h1{font-size:20px;margin-bottom:8px}
p.sub{color:#888;font-size:14px;margin-bottom:24px}
label{display:block;font-size:14px;margin-bottom:6px;color:#333}
input{width:100%;padding:10px 12px;border:1px solid #ddd;border-radius:8px;font-size:14px;margin-bottom:16px;outline:none}
input:focus{border-color:#1a73e8}
button{width:100%;padding:12px;background:#1a73e8;color:#fff;border:none;border-radius:8px;font-size:15px;cursor:pointer}
button:hover{background:#1557b0}
.result{margin-top:20px;padding:16px;border-radius:8px;display:none}
.result.success{display:block;background:#e8f5e9;color:#2e7d32}
.result.error{display:block;background:#fce8e6;color:#c5221f}
.key{font-family:monospace;font-size:13px;word-break:break-all;background:#fff;padding:8px;border-radius:6px;margin-top:8px}
</style></head>
<body>
<div class="card">
<h1>&#x9057;&#x5FD8;&#x5F15;&#x64CE;</h1>
<p class="sub">&#x6CE8;&#x518C;&#x5373;&#x83B7;&#x5F97; API key&#xFF0C;&#x514D;&#x8D39;&#x5F00;&#x59CB;&#x4F7F;&#x7528;</p>
<form id="form">
<label>&#x540D;&#x79F0;</label>
<input name="name" placeholder="&#x4F60;&#x7684;&#x540D;&#x5B57;&#x6216;&#x516C;&#x53F8;&#x540D;" autofocus>
<button type="submit">&#x6CE8;&#x518C;&#xFF0C;&#x83B7;&#x53D6; API Key</button>
</form>
<div id="result" class="result"></div>
</div>
<script>
document.getElementById('form').onsubmit=async function(e){e.preventDefault();
var r=document.getElementById('result');
r.className='result';r.innerHTML='...';
try{var res=await fetch('/register',{method:'POST',
headers:{'Content-Type':'application/x-www-form-urlencoded'},
body:'name='+encodeURIComponent(this.name.value)});
var d=await res.json();
if(d.error){r.className='result error';r.textContent=d.error}
else{r.className='result success';r.innerHTML='&#x6CE8;&#x518C;&#x6210;&#x529F;&#xFF01;&#x4F60;&#x7684; API key&#xFF1A;<div class=key>'+d.api_key+'</div><p style=margin-top:12px;font-size:13px>&#x4FDD;&#x5B58;&#x597D;&#x8FD9;&#x4E2A; key&#xFF0C;&#x540E;&#x7EED;&#x6240;&#x6709;&#x8C03;&#x7528;&#x90FD;&#x9700;&#x8981;&#x5B83;&#x3002;</p>'}
}catch(err){r.className='result error';r.textContent='&#x7F51;&#x7EDC;&#x9519;&#x8BEF;&#xFF0C;&#x8BF7;&#x91CD;&#x8BD5;'}};
</script></body></html>"""

store = TenantStore()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/register":
            self._html(PAGE)
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path == "/register":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            params = parse_qs(body)
            name = params.get("name", [""])[0]
            try:
                key = store.register(name)
                self._json(200, {"api_key": key})
            except Exception as e:
                self._json(500, {"error": str(e)})
        else:
            self.send_response(404); self.end_headers()

    def _html(self, content):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode())

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())


if __name__ == "__main__":
    port = int(os.getenv("WEB_PORT", "8001"))
    print(f"注册页面: http://0.0.0.0:{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

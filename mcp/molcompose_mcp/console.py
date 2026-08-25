"""A styled local web console for ChimeraX, replacing the bare REST test page.

Serves a single-page command console on localhost and proxies commands to the
ChimeraX ``remotecontrol rest`` bridge (same-origin, so no CORS issues). This
is the *human* command line — unlike the agent tool surface it applies no
whitelist, exactly like ChimeraX's own command prompt.
"""

import argparse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

CONSOLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MolCompose Console</title>
<style>
  :root {
    --accent: #4F46E5; --accent-dark: #4338CA; --bg: #F1F2F7;
    --card: #ffffff; --border: #E7E9F0; --ink: #2f323a; --hint: #7c7f88;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    display: flex; flex-direction: column; align-items: center;
    min-height: 100vh; padding: 24px;
  }
  .shell { width: min(860px, 100%); display: flex; flex-direction: column; gap: 14px; }
  header { display: flex; align-items: center; gap: 10px; }
  .dot { width: 12px; height: 12px; border-radius: 50%; background: var(--accent); }
  h1 { font-size: 18px; margin: 0; font-weight: 700; }
  .sub { color: var(--hint); font-size: 12px; margin-left: auto; }
  #output {
    background: #1F2430; color: #D9DCE3; border-radius: 12px;
    padding: 16px; height: 52vh; overflow-y: auto;
    font-family: Menlo, Consolas, monospace; font-size: 13px; line-height: 1.55;
    white-space: pre-wrap; word-break: break-word;
  }
  #output .cmd { color: #A5B4FC; font-weight: 600; }
  #output .err { color: #FCA5A5; }
  #output .hint { color: #8A8D96; }
  .inputrow {
    display: flex; gap: 8px; background: var(--card);
    border: 1px solid var(--border); border-radius: 12px; padding: 10px;
  }
  #command {
    flex: 1; border: none; outline: none; font-family: Menlo, Consolas, monospace;
    font-size: 14px; color: var(--ink); background: transparent;
  }
  button {
    border: none; border-radius: 9px; padding: 9px 18px; cursor: pointer;
    background: var(--accent); color: white; font-weight: 600; font-size: 13px;
  }
  button:hover { background: var(--accent-dark); }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; }
  .chip {
    background: #EEF2FF; color: var(--accent); border-radius: 14px;
    padding: 5px 12px; font-size: 12px; font-weight: 600; cursor: pointer;
  }
  .chip:hover { background: #E0E7FF; }
</style>
</head>
<body>
<div class="shell">
  <header>
    <div class="dot"></div>
    <h1>MolCompose Console</h1>
    <div class="sub">ChimeraX command line · Up/Down for history</div>
  </header>
  <div id="output"><span class="hint">Commands run inside ChimeraX.
Try a chip below, or any ChimeraX / molcompose command.</span>
</div>
  <div class="chips" id="chips">
    <span class="chip">open 1brs</span>
    <span class="chip">molcompose style complex-by-chain model #1</span>
    <span class="chip">molcompose interface A D model #1 distance 4.5</span>
    <span class="chip">molcompose style interface-focus model #1</span>
    <span class="chip">molcompose confidence model #1</span>
  </div>
  <div class="inputrow">
    <input id="command" placeholder="ChimeraX command…" autocomplete="off" autofocus>
    <button id="run">Run</button>
  </div>
</div>
<script>
  const output = document.getElementById("output");
  const input = document.getElementById("command");
  const history = [];
  let cursor = -1;

  function append(text, cls) {
    const span = document.createElement("span");
    if (cls) span.className = cls;
    span.textContent = text + "\\n";
    output.appendChild(span);
    output.scrollTop = output.scrollHeight;
  }

  function flatten(data) {
    const parts = [];
    const logs = data["log messages"];
    if (logs) for (const level of Object.values(logs)) {
      if (Array.isArray(level)) parts.push(...level.map(String));
    }
    if (data["error"]) parts.push("ERROR: " + data["error"]);
    return parts.join("\\n").replace(/<[^>]*>/g, "").trim();
  }

  async function run(command) {
    if (!command.trim()) return;
    append("❯ " + command, "cmd");
    history.unshift(command); cursor = -1;
    try {
      const response = await fetch("/run?" + new URLSearchParams({command}));
      const data = await response.json();
      const text = flatten(data);
      if (text) append(text, data["error"] ? "err" : "");
    } catch (error) {
      append("Cannot reach ChimeraX — is the bridge running? " +
             "(remotecontrol rest start port 3000 json true)", "err");
    }
    input.value = "";
  }

  document.getElementById("run").onclick = () => run(input.value);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") run(input.value);
    if (event.key === "ArrowUp" && cursor < history.length - 1) {
      cursor += 1; input.value = history[cursor];
    }
    if (event.key === "ArrowDown" && cursor > 0) {
      cursor -= 1; input.value = history[cursor];
    }
  });
  document.getElementById("chips").addEventListener("click", (event) => {
    if (event.target.classList.contains("chip")) run(event.target.textContent);
  });
</script>
</body>
</html>
"""


def build_proxy_url(chimerax_url: str, command: str) -> str:
    return f"{chimerax_url.rstrip('/')}/run?{urlencode({'command': command})}"


class ConsoleHandler(BaseHTTPRequestHandler):
    chimerax_url = "http://127.0.0.1:3000"

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(200, "text/html; charset=utf-8", CONSOLE_HTML.encode())
            return
        if parsed.path == "/run":
            command = parse_qs(parsed.query).get("command", [""])[0]
            try:
                with urlopen(  # noqa: S310 - localhost bridge
                    build_proxy_url(self.chimerax_url, command), timeout=300
                ) as response:
                    body = response.read()
                self._send(200, "application/json", body)
            except OSError as error:
                self._send(502, "application/json", f'{{"error": "{error}"}}'.encode())
            return
        self._send(404, "text/plain", b"not found")

    def log_message(self, *args):  # quiet server
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="MolCompose web console for ChimeraX")
    parser.add_argument("--port", type=int, default=8642)
    parser.add_argument(
        "--chimerax-url",
        default="http://127.0.0.1:3000",
        help="Base URL of the ChimeraX REST bridge (remotecontrol rest)",
    )
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    ConsoleHandler.chimerax_url = args.chimerax_url
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ConsoleHandler)
    address = f"http://127.0.0.1:{args.port}/"
    print(f"MolCompose Console on {address} (bridge: {args.chimerax_url})")
    if not args.no_browser:
        webbrowser.open(address)
    server.serve_forever()


if __name__ == "__main__":
    main()

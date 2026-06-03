"""
快速預覽 HTML 報告，不需重跑回測。
用法：
    python preview_report.py          # 預設 rule=Q
    python preview_report.py M        # 指定再平衡頻率
先在 Streamlit UI 跑一次回測產生 .last_run.pkl，之後每次改完 report_builder.py 直接跑此腳本。
"""
import pickle
import sys
import webbrowser
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".last_run.pkl"

if not CACHE.exists():
    print("❌ 找不到 .last_run.pkl，請先在 Streamlit UI 跑一次回測。")
    sys.exit(1)

rule = sys.argv[1] if len(sys.argv) > 1 else "Q"

with open(CACHE, "rb") as f:
    run_data = pickle.load(f)

from report_builder import build_html_report
html = build_html_report(run_data, rule)

out = ROOT / "report" / "_preview.html"
out.write_text(html, encoding="utf-8")
print(f"✅ 已產生：{out}")

# SSH 環境無法直接開瀏覽器，改用 HTTP server
# VS Code Remote SSH 會自動偵測並轉發 port → 本機瀏覽器開 http://localhost:8765
import http.server, threading, os

PORT = 8765
os.chdir(ROOT)

class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path in ("/", ""):
            self.path = "/report/_preview.html"
        super().do_GET()

def _serve():
    with http.server.HTTPServer(("", PORT), _Handler) as srv:
        srv.serve_forever()

threading.Thread(target=_serve, daemon=True).start()
print(f"🌐  http://localhost:{PORT}")
print("    （VS Code 會自動轉發 port，在本機瀏覽器開上面的網址）")
print("    Ctrl+C 結束")

import time
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n👋 已結束")

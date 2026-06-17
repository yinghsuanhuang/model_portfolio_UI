"""
快速預覽 HTML 報告，不需重跑回測。
用法：
    python preview_report.py                      # 預設 rule=Q、Gemini 摘要
    python preview_report.py M                     # 指定再平衡頻率
    python preview_report.py --tweak "日圓貶值風險講得更保守，字數壓到130字內"
    python preview_report.py --override-file my_summary.txt   # 整段定稿覆寫
先在 Streamlit UI 跑一次回測產生 .last_run.pkl，之後每次改完直接跑此腳本即可。
摘要微調只透過此 CLI，不會顯示在 UI 介面。
"""
import argparse
import os
import pickle
import sys
import warnings
from pathlib import Path

# 靜音 Google 套件的 FutureWarning（Python 版本／google.generativeai 棄用提醒，無害）
warnings.filterwarnings("ignore", category=FutureWarning)

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")  # 載入 GEMINI_API_KEY / ANTHROPIC_API_KEY，否則摘要會退回規則式
CACHE = ROOT / ".last_run.pkl"

if not CACHE.exists():
    print("❌ 找不到 .last_run.pkl，請先在 Streamlit UI 跑一次回測。")
    sys.exit(1)

_p = argparse.ArgumentParser(description="預覽 TAA HTML 報告")
_p.add_argument("rule", nargs="?", default="Q", help="再平衡頻率 M/Q/A/2Q-DEC")
_p.add_argument("--ai-provider", default="gemini",
                choices=["nlg", "gemini", "sonnet", "opus"])
_p.add_argument("--tweak", default=None,
                help="附加到摘要 prompt 的微調指令（自然語言，最高優先）")
_p.add_argument("--override-file", default=None,
                help="整段摘要定稿全文的檔案路徑（提供時跳過 LLM）")
_args = _p.parse_args()

rule = _args.rule
override_text = None
if _args.override_file:
    override_text = Path(_args.override_file).read_text(encoding="utf-8")

# 提醒：選了 LLM 卻缺 API key → 摘要會退回規則式，--tweak 不會生效
_key_needed = {"gemini": "GEMINI_API_KEY", "sonnet": "ANTHROPIC_API_KEY",
               "opus": "ANTHROPIC_API_KEY"}.get(_args.ai_provider)
if _key_needed and not os.environ.get(_key_needed) and override_text is None:
    print(f"⚠️  缺少 {_key_needed}，摘要將退回規則式（規則式不吃 --tweak）。"
          f"請確認 .env 已設定。", file=sys.stderr)

with open(CACHE, "rb") as f:
    run_data = pickle.load(f)

from report_builder import build_html_report
# 預設用 Gemini：依「月報文字」分頁 + 本期模型結論生成策略摘要
html = build_html_report(run_data, rule, ai_provider=_args.ai_provider,
                         summary_tweak=_args.tweak, summary_override=override_text)

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

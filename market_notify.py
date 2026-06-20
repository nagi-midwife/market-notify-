import yfinance as yf
import requests
import os
import json
from datetime import datetime
import pytz
import anthropic

# ── 環境変数 ──────────────────────────────
LINE_CHANNEL_TOKEN = os.environ.get("LINE_CHANNEL_TOKEN")   # チャネルアクセストークン
LINE_USER_ID       = os.environ.get("LINE_USER_ID")         # 送信先ユーザーID
ANTHROPIC_KEY      = os.environ.get("ANTHROPIC_API_KEY")
TAVILY_KEY         = os.environ.get("TAVILY_API_KEY")

# ── 取得対象 ──────────────────────────────
INDICES = [
    {"symbol": "^N225",   "name": "日経平均",     "group": "jp_stock"},
    {"symbol": "^TOPX",   "name": "TOPIX",        "group": "jp_stock"},
    {"symbol": "^TSE9",   "name": "東証グロース", "group": "jp_stock"},
    {"symbol": "^GSPC",   "name": "S&P500",       "group": "us_stock"},
    {"symbol": "^DJI",    "name": "NYダウ",       "group": "us_stock"},
    {"symbol": "^IXIC",   "name": "NASDAQ",       "group": "us_stock"},
]
FX = [
    {"symbol": "USDJPY=X", "name": "ドル円"},
    {"symbol": "EURUSD=X", "name": "ユーロドル"},
]
BONDS = [
    {"symbol": "^TNX",    "name": "米10年債利回り"},
    {"symbol": "^JGB10Y", "name": "日10年債利回り"},
]

# ── データ取得 ─────────────────────────────
def get_data(symbol):
    try:
        hist = yf.Ticker(symbol).history(period="5d")
        if len(hist) < 1:
            return None
        latest = hist.iloc[-1]
        prev   = hist.iloc[-2] if len(hist) >= 2 else None
        close  = latest["Close"]
        change     = close - prev["Close"] if prev is not None else 0
        change_pct = (change / prev["Close"] * 100) if prev is not None else 0
        return {"close": close, "change": change, "change_pct": change_pct}
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None

def fmt_line(name, data, decimals=2, bps=False):
    if data is None:
        return f"  {name}: 取得失敗"
    arrow = "▲" if data["change"] >= 0 else "▼"
    sign  = "+" if data["change"] >= 0 else ""
    close_str = f"{data['close']:,.{decimals}f}"
    if bps:
        diff = data["change"] * 100
        return f"{arrow} {name}\n  {close_str}%  ({sign}{diff:.1f}bps)"
    return f"{arrow} {name}\n  {close_str}  {sign}{data['change']:.{decimals}f} ({sign}{data['change_pct']:.2f}%)"

# ── ニュース取得（Tavily）─────────────────
def fetch_news():
    if not TAVILY_KEY:
        print("Tavily APIキーなし。スキップ。")
        return ""
    try:
        url = "https://api.tavily.com/search"
        queries = [
            "日経平均 株価 今日 理由",
            "ドル円 為替 今日",
            "米国株 S&P500 ナスダック 今日",
        ]
        all_results = []
        for q in queries:
            res = requests.post(url, json={
                "api_key": TAVILY_KEY,
                "query": q,
                "search_depth": "basic",
                "max_results": 3,
            }, timeout=10)
            if res.status_code == 200:
                for r in res.json().get("results", []):
                    all_results.append(f"・{r['title']}: {r.get('content','')[:150]}")
        return "\n".join(all_results[:9])
    except Exception as e:
        print(f"Tavily error: {e}")
        return ""

# ── Claude で解説＋クイズ生成 ────────────
def generate_commentary_and_quiz(market_summary: str, news: str) -> dict:
    empty = {"commentary": "", "question": "", "answer": ""}
    if not ANTHROPIC_KEY:
        return empty
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        prompt = f"""あなたはドラマ「相棒」の杉下右京警部です。
株・為替・債券市場の動向を、右京さんの口調で解説・出題してください。

【右京さんの口調の特徴】
- 丁寧語・敬語を使う（〜ですね、〜でしょう、〜ではないでしょうか）
- 論理的で回りくどいが、核心を突く
- 「実に興味深い」「ちょっと待ってください」「そうですねえ」などの口癖を自然に混ぜる
- 断定を避け「〜と考えられますねえ」「〜の可能性が高いとみております」などの表現を使う
- クイズは「一つ質問してもよろしいですか？」から始める
- 答えは「そうです、実は〜なんですよ」のように種明かし風に

以下のマーケットデータとニュースをもとに、JSONのみ返してください（前置き・コードブロック不要）。

【出力形式】
{{
  "commentary": "右京さん風の解説文（150字以内・右京さんの口癖を1〜2個含む）",
  "question": "右京さん風のクイズ（「一つ質問してもよろしいですか？」から始める・なぜ〜？という内容・1問）",
  "answer": "右京さん風の答えと解説（100字以内・種明かし風に）"
}}

【マーケットデータ】
{market_summary}

【関連ニュース】
{news if news else "ニュース取得なし"}
"""
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"Claude API error: {e}")
        return empty

# ── メッセージ組み立て ────────────────────
def format_message():
    jst = pytz.timezone("Asia/Tokyo")
    now = datetime.now(jst)
    date_str = now.strftime("%Y/%m/%d %H:%M")

    all_data = {}
    for item in INDICES + FX + BONDS:
        all_data[item["name"]] = get_data(item["symbol"])

    summary_lines = []
    for item in INDICES + FX + BONDS:
        d = all_data[item["name"]]
        if d:
            summary_lines.append(
                f"{item['name']}: {d['close']:.2f} ({'+' if d['change']>=0 else ''}{d['change_pct']:.2f}%)"
            )
    market_summary = "\n".join(summary_lines)

    news   = fetch_news()
    result = generate_commentary_and_quiz(market_summary, news)

    lines = [f"📊 マーケットサマリー", f"🕐 {date_str} JST"]

    lines += ["", "🇯🇵 日本株"]
    for i in [x for x in INDICES if x["group"] == "jp_stock"]:
        lines.append(fmt_line(i["name"], all_data[i["name"]]))

    lines += ["", "🇺🇸 米国株"]
    for i in [x for x in INDICES if x["group"] == "us_stock"]:
        lines.append(fmt_line(i["name"], all_data[i["name"]]))

    lines += ["", "💱 為替"]
    for fx in FX:
        dec = 4 if "ユーロ" in fx["name"] else 2
        lines.append(fmt_line(fx["name"], all_data[fx["name"]], decimals=dec))

    lines += ["", "🏦 債券利回り"]
    for b in BONDS:
        lines.append(fmt_line(b["name"], all_data[b["name"]], decimals=3, bps=True))

    if result["commentary"]:
        lines += ["", "🤖 AI解説", result["commentary"]]

    if result["question"]:
        lines += [
            "",
            "📝 今日の学習クイズ",
            result["question"],
            "",
            "💡 答え",
            result["answer"],
        ]

    return "\n".join(lines)

# ── LINE Messaging API で送信 ──────────────
def send_line_message(message: str):
    if not LINE_CHANNEL_TOKEN or not LINE_USER_ID:
        raise ValueError("LINE_CHANNEL_TOKEN または LINE_USER_ID が設定されていません")

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}",
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}],
    }
    res = requests.post(url, headers=headers, data=json.dumps(payload))
    if res.status_code == 200:
        print("✅ LINE送信成功")
    else:
        print(f"❌ 送信失敗: {res.status_code} {res.text}")
        res.raise_for_status()

# ── エントリーポイント ─────────────────────
if __name__ == "__main__":
    print("データ取得中...")
    message = format_message()
    print(message)
    send_line_message(message)

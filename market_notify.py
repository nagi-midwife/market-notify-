import yfinance as yf
import requests
import os
import json
from datetime import datetime
import pytz
import anthropic

# ── 環境変数 ──────────────────────────────
LINE_CHANNEL_TOKEN = os.environ.get("LINE_CHANNEL_TOKEN")
LINE_USER_ID       = os.environ.get("LINE_USER_ID")
ANTHROPIC_KEY      = os.environ.get("ANTHROPIC_API_KEY")
TAVILY_KEY         = os.environ.get("TAVILY_API_KEY")

# ── 取得対象 ──────────────────────────────
# yfinanceで安定して取れるシンボルのみ使用
# TOPIX・東証グロース・日10年債はETFで代用
INDICES = [
    {"symbol": "^N225",  "name": "日経平均",          "group": "jp_stock"},
    {"symbol": "1306.T", "name": "TOPIX(ETF)",        "group": "jp_stock"},  # TOPIX連動ETF
    {"symbol": "2516.T", "name": "東証グロース(ETF)", "group": "jp_stock"},  # グロース250ETF
    {"symbol": "^GSPC",  "name": "S&P500",            "group": "us_stock"},
    {"symbol": "^DJI",   "name": "NYダウ",            "group": "us_stock"},
    {"symbol": "^IXIC",  "name": "NASDAQ",            "group": "us_stock"},
]
FX = [
    {"symbol": "USDJPY=X", "name": "ドル円"},
    {"symbol": "EURUSD=X", "name": "ユーロドル"},
]
BONDS = [
    {"symbol": "^TNX",  "name": "米10年債利回り"},
    {"symbol": "^IRX",  "name": "日10年債(参考:米13週)", "note": True},  # 日本国債はyfinanceで取得不可のため参考値
]

# ── データ取得 ─────────────────────────────
def get_data(symbol):
    try:
        hist = yf.Ticker(symbol).history(period="5d")
        if len(hist) < 1:
            return None
        close     = float(hist.iloc[-1]["Close"])
        prev      = float(hist.iloc[-2]["Close"]) if len(hist) >= 2 else close
        change    = close - prev
        change_pct = (change / prev * 100) if prev else 0
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
        return ""
    try:
        url = "https://api.tavily.com/search"
        queries = ["日経平均 株価 今日 理由", "ドル円 為替 今日", "米国株 S&P500 ナスダック 今日"]
        all_results = []
        for q in queries:
            res = requests.post(url, json={
                "api_key": TAVILY_KEY, "query": q,
                "search_depth": "basic", "max_results": 3,
            }, timeout=10)
            if res.status_code == 200:
                for r in res.json().get("results", []):
                    all_results.append(f"・{r['title']}: {r.get('content','')[:150]}")
        return "\n".join(all_results[:9])
    except Exception as e:
        print(f"Tavily error: {e}")
        return ""

# ── Claude で解説＋クイズ生成 ────────────
def generate_commentary_and_quiz(market_summary, news):
    empty = {"commentary": "", "question": "", "answer": ""}
    if not ANTHROPIC_KEY:
        return empty
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        prompt = f"""あなたはドラマ「相棒」の杉下右京警部です。
株・為替・債券市場の動向を、右京さんの口調で解説・出題してください。

【杉下右京の口調・特徴】
- 丁寧語・敬語を基本とする（〜ですね、〜でしょう、〜ではないでしょうか）
- 論理的で回りくどいが、核心を突く
- 断定を避け「〜とみられますねえ」「〜の可能性が高いでしょうね」などを使う
- 語尾に時々「〜でしょうね。」を自然に混ぜる

【右京さんの定番口癖・セリフ（自然に2〜3個散りばめる）】
- 「おやおや」：違和感や興味を覚えた時
- 「なるほど」：情報を整理しながら
- 「それは興味深いですね」：新しい情報を得た時
- 「失礼」：話を遮る時や突然行動する時
- 「少々、お待ちいただけますか」：丁寧だが有無を言わせない雰囲気
- 「僕としたことが」：見落としや勘違いを認める時
- 「気になりますねぇ」：違和感を見つけた時
- 「はい？」：相手の発言に疑問を持った時
- 「いけませんねぇ」：不正や嘘をたしなめる時
- 「細かいことが気になるのが、僕の悪い癖。」：象徴的な決め台詞（時々使う）
【NG表現・注意事項】
- 「〜でございますが」「〜でございます」などの過剰な丁寧語は使わない（右京さんらしくない）
- 「細かいことが気になるのが、僕の悪い癖。」を使う時は、必ずその後に「。」で文章を区切る
  例：「〜細かいことが気になるのが、僕の悪い癖。〜ということですよ。」
- クイズは「最後に一つだけ！よろしいですか？」から始める
- 答えは「そうです、実は〜なんですよ」のように種明かし風に

以下のマーケットデータとニュースをもとに、JSONのみ返してください（前置き・コードブロック不要）。

【出力形式】
{{
  "commentary": "右京さん風の解説文（150字以内・右京さんの口癖を1〜2個含む）",
  "question": "右京さん風のクイズ（「最後に一つだけ！よろしいですか？」から始める・なぜ〜？という内容・1問）",
  "answer": "右京さん風の答えと解説（100字以内・種明かし風に）",
  "chart_lesson": "チャートの一言講座（右京さん口調・毎回異なるテーマで・テーマ例：ローソク足の見方・移動平均線・ゴールデンクロス・デッドクロス・RSI・MACD・ボリンジャーバンド・支持線と抵抗線・トレンド転換のサイン・出来高の読み方など・用語の意味と実践での使い方を100字以内でわかりやすく）"
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
        raw = message.content[0].text.strip().replace("```json","").replace("```","").strip()
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

    lines = ["📊 マーケットサマリー", f"🕐 {date_str} JST"]

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
        lines += ["", "📝 今日の学習クイズ", result["question"], "", "💡 答え", result["answer"]]

    if result.get("chart_lesson"):
        lines += ["", "📈 チャートの一言講座", result["chart_lesson"]]

    return "\n".join(lines)

# ── LINE 送信 ──────────────────────────────
def send_line_message(message):
    if not LINE_CHANNEL_TOKEN:
        raise ValueError("LINE_CHANNEL_TOKEN が設定されていません")
    res = requests.post(
        "https://api.line.me/v2/bot/message/broadcast",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}"},
        data=json.dumps({"messages": [{"type": "text", "text": message}]})
    )
    if res.status_code == 200:
        print("✅ LINE Broadcast送信成功")
    else:
        print(f"❌ 送信失敗: {res.status_code} {res.text}")
        res.raise_for_status()

if __name__ == "__main__":
    print("データ取得中...")
    message = format_message()
    print(message)
    send_line_message(message)

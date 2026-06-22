import requests
import os
import json
from datetime import datetime
import pytz
import anthropic

# ── 環境変数 ──────────────────────────────
LINE_CHANNEL_TOKEN = os.environ.get("LINE_CHANNEL_TOKEN")
ANTHROPIC_KEY      = os.environ.get("ANTHROPIC_API_KEY")
TAVILY_KEY         = os.environ.get("TAVILY_API_KEY")

# ── 午前相場ニュース取得（Tavily）─────────
def fetch_morning_news():
    if not TAVILY_KEY:
        print("Tavily APIキーなし。スキップ。")
        return ""
    try:
        queries = [
            "東京株式市場 午前 今日 セクター",
            "日経平均 午前 今日 上昇 下落 材料",
            "日本株 今日 資金 業種 注目",
        ]
        all_results = []
        for q in queries:
            res = requests.post("https://api.tavily.com/search", json={
                "api_key": TAVILY_KEY,
                "query": q,
                "search_depth": "basic",
                "max_results": 4,
            }, timeout=10)
            if res.status_code == 200:
                for r in res.json().get("results", []):
                    all_results.append(f"・{r['title']}: {r.get('content','')[:200]}")
        return "\n".join(all_results[:12])
    except Exception as e:
        print(f"Tavily error: {e}")
        return ""

# ── Claude で午前相場レポート生成 ──────────
def generate_midday_report(news: str) -> str:
    if not ANTHROPIC_KEY:
        return ""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        jst = pytz.timezone("Asia/Tokyo")
        today = datetime.now(jst).strftime("%Y年%m月%d日")

        prompt = f"""あなたはドラマ「相棒」の杉下右京警部です。
今日（{today}）の東京市場・午前の相場について、右京さんの口調でレポートしてください。

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
- 「細かいことが気になるのが、僕の悪い癖でしてね」：象徴的な決め台詞（時々使う）
- レポートの締めに時々「最後に一つだけ！よろしいですか？」と前置きしてから午後相場への注目点を一言添える

【レポートに含めること】
1. 午前相場の全体感（強い・弱い・まちまち）
2. 資金が集まっているセクター・業種（例：半導体、銀行、内需など）
3. 売られているセクター・業種
4. 動きの背景にある材料・ニュース
5. 午後相場への一言コメント

【制約】
- 全体で300字以内
- 箇条書き禁止、自然な会話文で
- 右京さんの口癖を2〜3個含める

【関連ニュース】
{news if news else "ニュース取得なし（一般的な午前相場の傾向で解説してください）"}
"""
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        print(f"Claude API error: {e}")
        return ""

# ── メッセージ組み立て ────────────────────
def format_message():
    jst = pytz.timezone("Asia/Tokyo")
    now = datetime.now(jst)
    date_str = now.strftime("%Y/%m/%d %H:%M")

    news   = fetch_morning_news()
    report = generate_midday_report(news)

    lines = [
        "🗾 午前相場レポート",
        f"🕐 {date_str} JST",
        "",
        "🤖 右京さんの解説",
        report if report else "データ取得に失敗しました。",
    ]
    return "\n".join(lines)

# ── LINE Broadcast送信 ────────────────────
def send_line_message(message: str):
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

# ── エントリーポイント ─────────────────────
if __name__ == "__main__":
    print("午前相場レポート生成中...")
    message = format_message()
    print(message)
    send_line_message(message)

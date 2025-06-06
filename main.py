# version: v1.8.0
# description: LINEレシピBot本体コード。GPT-3.5を使って気分に合う5つの料理を提案し、選ばれた1つの詳細レシピを返す。ボタンは料理名のみ表示、Flexで縦並び。サマリーも表示可。

import os
import time
import threading
import re  # ファイル上部に追加
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
)
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
app = Flask(__name__)

line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

user_sessions = {}

def generate_recipe_prompt(user_msg):
    if "スイーツ" in user_msg or "デザート" in user_msg:
        category = "Japanese desserts"
    elif "ドリンク" in user_msg or "飲み物" in user_msg:
        category = "Japanese drinks"
    else:
        category = "Japanese meals"

    prompt = f"""
The user says: "{user_msg}"
Please suggest 5 {category} based on this mood.
Each suggestion must include:
- title
- a brief reason why it fits the mood
- one overall summary sentence (1 short line) about the general theme of the suggestions, such as "These recipes are refreshing and help cool down on a hot day."

Respond only in Japanese.
Avoid generic items like coffee, udon, or somen unless user asked.
Avoid drinks or desserts unless requested.
Use common ingredients and simple ideas, but make at least one feel new or clever.
"""
    return prompt

def generate_detail_prompt(title):
    return f"""
You are a Japanese cooking expert. Please write a full recipe for the following item.

【Dish】{title}

Language rules:
- If the title is in Japanese, respond entirely in Japanese.
- If the title is in English, respond entirely in English.

Recipe should include:

1. How many servings it makes (e.g., 2〜3人前)
2. List of ingredients using simple units:
   - Use friendly measurements like "a little", "1 handful", "1 piece"
   - Avoid using grams (g), milliliters (ml), or complex cooking terms
3. Step-by-step instructions (max 7 steps):
   - Add brief explanations **only where it's especially helpful or interesting**
     (e.g., "Start with skin side down to make it crispy")
   - If the recipe allows shortcuts (e.g., pre-made tempura for tendon), include that as an option
4. At the end, include a fun or useful fact about the dish
   - Make it light and friendly
   - Start with one of the following headers (choose randomly): 
     「料理の小ネタ」, 「知ってると話したくなる話」, 「この料理、実は…」, 「ちょこっと豆知識」, 「豆メモ」

This rule applies to:
- Meals
- Desserts (スイーツ / sweets)
- Drinks (ドリンク / beverages)

Be concise, clear, and beginner-friendly.
"""

def build_flex_message(user_msg, recipes):
    seen_titles = set()
    buttons = []

    for i, item in enumerate(recipes):
        raw_title = item.get("title", "レシピ").strip()
        # 先頭の番号・句読点（例: 1. 明太子パスタ）を除去
        title = re.sub(r"^[0-9]+[.:：\\s]*", "", raw_title)[:20]

        if not title or title in seen_titles:
            continue
        seen_titles.add(title)

        buttons.append({
            "type": "button",
            "action": {
                "type": "message",
                "label": f"{i+1}. {title}",
                "text": f"{i+1}"
            },
            "style": "primary",
            "margin": "sm"
        })

    bubble = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": f"「{user_msg}」にぴったりなレシピ、選んでね👇",
                    "weight": "bold",
                    "size": "md",
                    "wrap": True
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": buttons
        }
    }

    return FlexSendMessage(alt_text="レシピの提案です", contents=bubble)

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    threading.Thread(target=handle_event_async, args=(body, signature)).start()
    return "OK"

def handle_event_async(body, signature):
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("❌ Invalid signature")

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_msg = event.message.text.strip()

    if user_id in user_sessions:
        if user_msg.isdigit():
            index = int(user_msg) - 1
            if 0 <= index < len(user_sessions[user_id]):
                selected = user_sessions[user_id][index]
                detail_prompt = generate_detail_prompt(selected["title"])
                try:
                    print("🔁 GPTに詳細レシピを問い合わせ中...")
                    reply = openai_client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "user", "content": detail_prompt}]
                    )
                    detailed_recipe = reply.choices[0].message.content
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=f"{selected['title']} の作り方です：\n\n{detailed_recipe}")
                    )
                except Exception as e:
                    print(f"❌ GPTエラー発生: {e}")
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text="レシピ取得に失敗しました。後でもう一度お試しください。")
                    )
                del user_sessions[user_id]
                return

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="メッセージ受け取りました。考え中です…🤔")
    )

    try:
        start = time.time()
        prompt = generate_recipe_prompt(user_msg)
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        content = response.choices[0].message.content.strip()
        elapsed = time.time() - start

        lines = content.split("\n")
        recipes = []
        for line in lines:
            if line.strip() == "":
                continue
            if line[0].isdigit():
                parts = line.split("：", 1) if "：" in line else line.split(":", 1)
                if len(parts) > 1:
                    title = parts[1].strip().split("。", 1)[0].split(".", 1)[0]
                else:
                    title = parts[0].strip()
                recipes.append({"title": title, "reason": ""})
            elif recipes:
                recipes[-1]["reason"] += line.strip() + " "

        # Remove trailing whitespace from reason
        for r in recipes:
            r["reason"] = r["reason"].strip()

        user_sessions[user_id] = recipes[:5]
        flex_msg = build_flex_message(user_msg, user_sessions[user_id])

        summary_line = ""
        if recipes and recipes[-1]['reason'].startswith("全体の傾向："):
            summary_line = recipes.pop()['reason'].replace("全体の傾向：", "")

        if summary_line:
            line_bot_api.push_message(
                user_id,
                [TextSendMessage(text=summary_line), flex_msg]
            )
        else:
            line_bot_api.push_message(
                user_id,
                [flex_msg]
            )
    except Exception as e:
        print(f"❌ GPTエラー発生: {e}")
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text="ちょっと調子が悪いみたいです💦 また後で試してみてください🙏")
        )

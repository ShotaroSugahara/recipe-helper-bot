import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from dotenv import load_dotenv
from utils.usage_tracker import check_usage, increment_usage
from openai import OpenAI

load_dotenv()

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id

    if not check_usage(user_id):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="今日はもう5回使いました！また明日どうぞ🍳")
        )
        return

    user_msg = event.message.text

    prompt = f"ユーザーの気分は「{user_msg}」。この気分に合うレシピを3つ提案してください。それぞれに、料理名、調理時間（★1〜5）、コスト（★1〜5）を含めてください。"

    try:
        chat_completion = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        reply_text = chat_completion.choices[0].message.content
    except Exception as e:
        reply_text = f"[エラー発生]\n{str(e)}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

    increment_usage(user_id)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

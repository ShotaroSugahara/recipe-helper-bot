from dotenv import load_dotenv
load_dotenv()
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
import os
import openai
from utils.usage_tracker import check_usage, increment_usage

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
openai.api_key = os.environ["OPENAI_API_KEY"]

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
            TextSendMessage(text="今日はもう5回使いました！また明日お試しください🍳")
        )
        return

    user_msg = event.message.text

    prompt = f"ユーザーの気分は「{user_msg}」。この気分に合うレシピを3つ提案してください。それぞれに、料理名、調理時間（★1〜5）、コスト（★1〜5）を含めてください。"

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )

    reply_text = response.choices[0].message.content

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

    increment_usage(user_id)

if __name__ == "__main__":
    app.run()

import os, requests
BOT = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT = os.getenv('TELEGRAM_CHAT_ID')
print(f"BOT: {BOT[:10]}... CHAT: {CHAT}")
url = f"https://api.telegram.org/bot{BOT}/sendMessage"
r = requests.get(url, params={"chat_id": CHAT, "text": "✅ V59 Scanner Telegram OK! Market उद्या 9:15 ला सुरू झाल्यावर Signal येईल!"})
print(r.text)

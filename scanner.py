import os, time, requests, pyotp
from datetime import datetime, timedelta
from SmartApi import SmartConnect

API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")
PASSWORD = os.getenv("ANGEL_PASSWORD")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_tg(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg}, timeout=10)
        print("TG Sent")
    except Exception as e:
        print(f"TG Fail {e}")

def main():
    try:
        obj = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_SECRET).now()
        obj.generateSession(CLIENT_ID, PASSWORD, totp)
        print("LOGIN OK")
    except Exception as e:
        print(f"Login Fail {e}")
        return

    SYMBOLS = ["RECLTD", "UNIONBANK", "SBIN", "RELIANCE", "BHARTIARTL", "ITC"]

    for sym in SYMBOLS:
        try:
            # LIVE TOKEN - No Hardcode
            search = obj.searchScrip("NSE", sym)
            token = None
            for it in search['data']:
                if it.get('tradingsymbol') == f"{sym}-EQ":
                    token = it.get('symboltoken')
                    break
            if not token:
                token = search['data'][0]['symboltoken']

            # REAL TIME LTP - Current Market
            ltp_resp = obj.ltpData("NSE", f"{sym}-EQ", token)
            ltp = ltp_resp['data']['ltp']

            print(f"LIVE {sym} | Token {token} | LTP {ltp} | {datetime.now().strftime('%H:%M:%S')}")

            # TEST TELEGRAM FOR REC - Rate Check
            if sym == "RECLTD":
                send_tg(f"✅ LIVE REAL TIME\n{sym}: ₹{ltp} (Correct Rate)\nToken: {token}\nTime: {datetime.now().strftime('%d-%b %H:%M:%S')}\nRate Limit Fix OK!")

            time.sleep(1.2) # Rate Limit Fix - Must!

        except Exception as e:
            err = str(e)
            if "exceeding" in err.lower() or "rate" in err.lower():
                print("Rate Limit - Waiting 70 sec")
                time.sleep(70)
                continue
            if "AB4046" in err:
                print(f"Skip {sym} token error")
                continue
            print(f"{sym} Error {e}")

if __name__ == "__main__":
    main()

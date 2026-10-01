import os, time, requests, pyotp, pytz
from datetime import datetime, timedelta
from SmartApi import SmartConnect
import math

# --- CONFIG ---
API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")
PASSWORD = os.getenv("ANGEL_PASSWORD")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOLS = ["SCHNEIDER", "IDBI", "WELSPUNLIV", "RECLTD", "UNIONBANK", "SBIN", "RELIANCE", "BHARTIARTL"]

def send_tg(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except: pass

def ema_calc(prices, period):
    ema = [sum(prices[:period])/period]
    k = 2/(period+1)
    for p in prices[period:]:
        ema.append(p*k + ema[-1]*(1-k))
    return ema[-1]

def rsi_calc(prices, period=14):
    deltas = [prices[i+1]-prices[i] for i in range(len(prices)-1)]
    gains = [d if d>0 else 0 for d in deltas]
    losses = [-d if d<0 else 0 for d in deltas]
    avg_gain = sum(gains[:period])/period
    avg_loss = sum(losses[:period])/period
    if avg_loss == 0: return 85
    for i in range(period, len(gains)):
        avg_gain = (avg_gain*(period-1)+gains[i])/period
        avg_loss = (avg_loss*(period-1)+losses[i])/period
    rs = avg_gain/(avg_loss+0.0001)
    return 100 - (100/(1+rs))

def main():
    obj = SmartConnect(api_key=API_KEY)
    totp = pyotp.TOTP(TOTP_SECRET).now()
    obj.generateSession(CLIENT_ID, PASSWORD, totp)
    print("LOGIN OK - Scanner Started 9:15-15:00")

    ist = pytz.timezone('Asia/Kolkata')

    for sym in SYMBOLS:
        try:
            # 1. LIVE TOKEN + LTP (Rate Limit Fix)
            search = obj.searchScrip("NSE", sym)
            token = None
            for it in search['data']:
                if it.get('tradingsymbol') == f"{sym}-EQ":
                    token = it.get('symboltoken')
                    break
            if not token: continue

            # 2. 5 Min Candle Data - Last 50 Candles
            from_date = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
            to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
            hist = obj.getCandleData({"exchange":"NSE","symboltoken":token,"interval":"FIVE_MINUTE","fromdate":from_date,"todate":to_date})
            candles = hist['data']
            if len(candles) < 20: continue

            closes = [c[4] for c in candles]
            volumes = [c[5] for c in candles]
            highs = [c[2] for c in candles]
            lows = [c[3] for c in candles]

            # 3. INDICATORS (तुझ्या 3 Photo वरून)
            ltp = closes[-1]
            prev_close = closes[-2]
            second_high = highs[-2] # 2nd Candle High - V59 Core
            second_low = lows[-2]

            ema9 = ema_calc(closes, 9)
            ema15 = ema_calc(closes, 15)
            vwap = sum(closes[-15:]) / 15 # Simple VWAP approx
            rsi = rsi_calc(closes)
            avg_vol = sum(volumes[-15:-1]) / 14
            curr_vol = volumes[-1]

            # 4. TIME FILTER - 9:15 to 3:00 PM
            now_time = datetime.now(ist).strftime("%H:%M")
            if not ("09:15" <= now_time <= "15:00"):
                print(f"Market बंद {now_time}")
                break

            # 5. FINAL CONDITION - 3 Photo Logic Combine
            # SCHNEIDER Type + IDBI Bullish Engulfing + WELSPUNLIV Exit Logic

            # FAKE 1000 Share Filter
            if curr_vol < 25000:
                print(f"SKIP {sym} - खोटा Moment - Vol {curr_vol} < 25000")
                time.sleep(1.5)
                continue

            # A) REAL BUY MOMENT (SCHNEIDER + IDBI)
            # Price > 2nd High + EMA Bullish + RSI 60-75 + Volume Spike
            is_buy = (ltp > second_high) and (ema9 > ema15 > vwap) and (60 <= rsi <= 78) and (curr_vol > avg_vol*1.5)

            # B) EXIT MOMENT (WELSPUNLIV Type)
            is_exit = (ltp < ema9) and (rsi < 55) and (prev_close > ema9)

            if is_buy:
                msg = f"🔥 5 MIN LIVE BUY\n{sym} @ {ltp}\n> 2nd High {second_high}\nRSI {rsi:.1f} EMA {ema9:.1f}>{ema15:.1f}\nVol {curr_vol} > 25k\nTime {now_time}"
                send_tg(msg)
                print(msg)

            if is_exit:
                msg = f"⚠️ EXIT SIGNAL\n{sym} @ {ltp} - Moment Over\nRSI {rsi:.1f} < 55"
                send_tg(msg)
                print(msg)

            time.sleep(1.5) # Rate Limit Fix - MUST

        except Exception as e:
            print(f"{sym} Error {e}")
            if "exceed" in str(e).lower():
                time.sleep(70)
            continue

if __name__ == "__main__":
    main()

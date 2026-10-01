import os, requests, pyotp, time
from SmartApi import SmartConnect
from datetime import datetime
import pytz

API_KEY=os.getenv("ANGEL_API_KEY","").strip()
CLIENT_ID=os.getenv("ANGEL_CLIENT_ID","").strip()
PASSWORD=os.getenv("ANGEL_PASSWORD","").strip()
TOTP_SECRET=os.getenv("ANGEL_TOTP_SECRET","").strip()
BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","").strip()

def send_tg(t):
    try:
        url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id":CHAT_ID, "text":t}, timeout=15)
    except: pass
    print(t)

def calc_ema(d,p):
    if len(d)<p: return None
    k=2/(p+1); e=sum(d[:p])/p
    for x in d[p:]: e=x*k+e*(1-k)
    return e

def calc_rsi(c,p=14):
    if len(c)<p+1: return 50
    g=l=0
    for i in range(1,p+1):
        d=c[-i]-c[-i-1]
        if d>0: g+=d
        else: l-=d
    return 75 if l==0 else 100-(100/(1+g/l))

def calc_vwap(candles):
    pv=vv=0
    for c in candles[-20:]:
        tp=(float(c[2])+float(c[3])+float(c[4]))/3
        v=float(c[5]); pv+=tp*v; vv+=v
    return pv/vv if vv else 0

print("=== V59 SECOND CANDLE HIGH-LOW START ===")
smart=SmartConnect(api_key=API_KEY)
smart.generateSession(CLIENT_ID,PASSWORD,pyotp.TOTP(TOTP_SECRET).now())
print("Login OK")

ist=pytz.timezone('Asia/Kolkata')
now=datetime.now(ist)
tstr=now.strftime('%d-%b %I:%M %p IST')

# Tokens - UNIONBANK 172 चा खरा
STOCKS={"RITES":"3045","SUNTV":"4244","UNIONBANK":"2827","BLEL":"5330","IRCON":"17477","PFC":"633","RVNL":"15384","RECLTD":"15332"}

for sym,token in STOCKS.items():
    try:
        time.sleep(1)
        ltp=float(smart.ltpData("NSE",sym,token)['data']['ltp'])
        params={"exchange":"NSE","symboltoken":token,"interval":"FIVE_MINUTE","fromdate":now.replace(hour=9,minute=15).strftime("%Y-%m-%d %H:%M"),"todate":now.strftime("%Y-%m-%d %H:%M")}
        candles=smart.getCandleData(params).get('data',[])
        if len(candles)<20: continue

        closes=[float(c[4]) for c in candles]; highs=[float(c[2]) for c in candles]; lows=[float(c[3]) for c in candles]; vols=[float(c[5]) for c in candles]
        ema9=calc_ema(closes,9); ema15=calc_ema(closes,15); vwap=calc_vwap(candles); rsi=calc_rsi(closes)
        avg_vol=sum(vols[-10:-1])/9 if len(vols)>10 else vols[-1]

        sec_high=highs[-2]; sec_low=lows[-2]
        bottom_zone=min(lows[-10:])*1.015
        top_zone=max(highs[-10:])*0.985

        bottom_buy = (lows[-2] <= bottom_zone and ltp > sec_high and ema9 > ema15 and ema9 > vwap and 55 <= rsi <= 75 and vols[-1] > avg_vol*1.2)
        top_sell = (highs[-2] >= top_zone and ltp < sec_low and ema9 < ema15 and rsi >= 68 and vols[-1] > avg_vol*1.2)

        print(f"{sym} LTP:{ltp} 2H:{sec_high} 2L:{sec_low} RSI:{rsi:.1f} BUY:{bottom_buy} SELL:{top_sell}")

        if bottom_buy:
            sl=sec_low*0.99; risk=ltp-sl
            send_tg(f"🟢 2ND HIGH BUY @ BOTTOM {sym}\nTime:{tstr}\nLTP:{ltp:.2f} > 2nd High:{sec_high:.2f} ✅\n2nd Low:{sec_low:.2f}=SL\n9EMA:{ema9:.2f}>15EMA:{ema15:.2f}>VWAP:{vwap:.2f}\nRSI:{rsi:.1f} VOL Spike\n---\nBUY:{ltp:.2f}\nSL:{sl:.2f} (2nd Low)\nTSL:15EMA Trail\nTGT1:{ltp+risk:.2f} TGT2:{ltp+risk*2.5:.2f}\nRR 1:2.5")

        if top_sell:
            sl=sec_high*1.01; risk=sl-ltp
            send_tg(f"🔴 2ND LOW SELL @ TOP {sym}\nTime:{tstr}\nLTP:{ltp:.2f} < 2nd Low:{sec_low:.2f} ✅\n2nd High:{sec_high:.2f}=SL\n9EMA:{ema9:.2f}<15EMA\nRSI:{rsi:.1f}\n---\nSELL:{ltp:.2f}\nSL:{sl:.2f} (2nd High)\nTSL:9EMA Trail\nTGT1:{ltp-risk:.2f} TGT2:{ltp-risk*2:.2f}")

    except Exception as e:
        print(f"{sym} {e}")

print("V59 DONE")

import os, sys, pytz, requests, pandas as pd, pyotp, json
from datetime import datetime, timedelta, time
from SmartApi import SmartConnect
from concurrent.futures import ThreadPoolExecutor
try: import websocket
except: os.system(f"{sys.executable} -m pip install websocket-client -q")

IST = pytz.timezone("Asia/Kolkata")
POS_FILE = "positions.json"

# Smallcap 400 FAST - No ZOMATO Error
SMALLCAP_400 = ["5PAISA","KALYANKJIL","SMCGLOBAL","NUVAMA","NETWEB","PWL","SCI","ESCORTS","MAZDOCK","GRSE","COCHINSHIP","BDL","DATAPATTNS","MTARTECH","SWANENERGY","IDEA","SUZLON","YESBANK","RPOWER","IRB","HCC","GMRINFRA","SOUTHBANK","FEDERALBNK","IDFCFIRSTB","BANDHANBNK","RBLBANK","PNB","BANKBARODA","CANBK","ANGELONE","BSE","CDSL","MCX","IRCTC","ETERNAL","PAYTM","BHEL","BEL","HAL","SAIL","VEDL","TATASTEEL","JSWSTEEL","TATAPOWER","ADANIPOWER","NHPC","POWERGRID","NTPC","REC","PFC","IRFC","RVNL","TITAN","TATAMOTORS","M&M","MARUTI","INDIGO","RAYMOND","HAPPSTMNDS","GODREJAGRO","KSB","TRIDENT","JPOWER","HFCL","KPITTECH","KFINTECH","ANANDRATHI","IDEAFORGE","SENCO","UTKARSHBNK","SBFC","RRKABEL","JSWINFRA","BLS","EASEMYTRIP","NYKAA","DELHIVERY","POLICYBZR","CARTRADE","FSL","ROUTE","MASTEK","PERSISTENT","COFORGE","MPHASIS","LTTS","CYIENT","AFFLE","TANLA","KALYANJEWEL","MANAPPURAM","CREDITACC","UJJIVAN","AUBANK","HOMEFIRST","PNBHOUSING","BHARATDYNAM","BEML","PARAS","AZAD","DCXINDIA","HINDUSTANZINC","NATIONALUM","SAIL","JINDALSTEL","NMDC","JSWENERGY","IRCON","RITES","NCC","KNRCON","LTF","HUDCO","EIL","THERMAX","ABB","SIEMENS","PRAJIND","MM","SONACOMS","ENDURANCE","JKTYRE","CEAT","APOLLOTYRE","BHARATFORG","TIINDIA","JUBLFOOD","DEVYANI","AVANTIFEED","BALRAMCHIN","BATA","RELAXO","VIPIND","GHCL","ALOKINDS","LUX","DOLLAR","PAGEIND","KPRMILL","AJANTA","LAURUSLABS","GRANULES","NATCOPHARM","LUPIN","CIPLA","DIVISLAB","ZYDUSLIFE","BIOCON","LALPATHLAB","APOLLOHOSP","MAXHEALTH","ASTRAL","SRF","NAVINFLUOR","AARTIIND","ATUL","CLEAN","DIXON","PGEL","KAYNES","AWL","PATANJALI","GODREJCP","MARICO","TITAN"]

def calculate_indicators(df):
    """तुझंच - EMA9, EMA15, VWAP, RSI - No ta library"""
    df["EMA_9"] = df["c"].ewm(span=9).mean()
    df["EMA_15"] = df["c"].ewm(span=15).mean()
    d = df["c"].diff(); g = d.clip(lower=0); l = -d.clip(upper=0)
    rs = g.ewm(alpha=1/14).mean() / l.ewm(alpha=1/14).mean()
    df["RSI"] = 100 - (100/(1+rs))
    tp = (df["h"]+df["l"]+df["c"])/3
    df["VWAP"] = (tp*df["v"]).cumsum()/df["v"].cumsum()
    df["Vol_Avg_10"] = df["v"].rolling(10).mean()
    return df

def generate_final_signal(args):
    obj, sym, tmap, positions = args
    try:
        tok = tmap.get(sym)
        if not tok: return None
        to_d = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
        from_d = (datetime.now(IST)-timedelta(days=15)).strftime("%Y-%m-%d %H:%M")
        r = obj.getCandleData({"exchange":"NSE","symboltoken":tok,"interval":"FIVE_MINUTE","fromdate":from_d,"todate":to_d})
        if not r or not r.get('data') or len(r['data'])<50: return None

        df = pd.DataFrame(r['data'],columns=['dt','o','h','l','c','v'])
        for c in ['o','h','l','c','v']: df[c]=pd.to_numeric(df[c],errors='coerce')
        df['dt']=pd.to_datetime(df['dt'])
        today=datetime.now(IST).strftime("%Y-%m-%d")
        dft=df[df['dt'].dt.strftime("%Y-%m-%d")==today].copy().reset_index(drop=True)
        if len(dft)<15: return None

        dft = calculate_indicators(dft)
        curr = dft.iloc[-1]
        ltpr = obj.ltpData("NSE",sym+"-EQ",tok)
        ltp = ltpr['data']['ltp'] if ltpr and ltpr.get('data') else curr['c']
        now = datetime.now(IST)

        # --- 1. POSITION असेल तर 50% BOOK + 2.5 + TRAIL + 3:15 EXIT ---
        if sym in positions:
            pos = positions[sym]
            entry, risk = pos['entry'], pos['risk']
            profit_r = (ltp-entry)/risk if risk>0 else 0

            if now.hour==15 and now.minute>=15:
                del positions[sym]
                return {"type":"EXIT_315","sym":sym,"ltp":ltp,"msg":f"3:15 FINAL EXIT @ {ltp:.1f} P&L {profit_r:.1f}R"}

            trail_sl = pos.get('trail_sl', pos['sl'])
            if profit_r >= 1.5:
                trail_sl = round(dft.iloc[-2:]['l'].min()*0.998,2)
            elif profit_r >= 1.0:
                trail_sl = entry

            positions[sym]['trail_sl']=trail_sl
            positions[sym]['r']=profit_r
            positions[sym]['ltp']=ltp

            if profit_r >= 1.25 and not pos.get('booked_50'):
                positions[sym]['booked_50']=True
                return {"type":"BOOK_50","sym":sym,"ltp":ltp,"msg":f"50% BOOK @ {ltp:.1f} {profit_r:.1f}R Trail {trail_sl}"}

            if ltp <= trail_sl:
                del positions[sym]
                return {"type":"SL_HIT","sym":sym,"ltp":ltp,"msg":f"SL HIT Trail {trail_sl}"}

            if profit_r >= 2.5:
                del positions[sym]
                return {"type":"TGT_2.5","sym":sym,"ltp":ltp,"msg":f"FINAL TGT 2.5x HIT @ {ltp:.1f} {profit_r:.1f}R"}

            return None

        # --- 2. NEW BUY - फक्त 9:15 to 3:30 ---
        if not (9 <= now.hour <= 15): return None
        if now.hour==9 and now.minute<20: return None
        if now.hour==15 and now.minute>30: return None

        avg10 = curr['Vol_Avg_10'] if pd.notna(curr['Vol_Avg_10']) else dft['v'].mean()

        breakout=None
        for i in range(1, len(dft)):
            prev_ema9 = dft.iloc[i-1]['EMA_9']; prev_vwap = dft.iloc[i-1]['VWAP']
            curr_ema9 = dft.iloc[i]['EMA_9']; curr_vwap = dft.iloc[i]['VWAP']
            curr_close = dft.iloc[i]['c']; curr_ema15 = dft.iloc[i]['EMA_15']
            if pd.isna(prev_ema9) or pd.isna(prev_vwap): continue
            if prev_ema9 <= prev_vwap and curr_ema9 > curr_vwap and curr_close > curr_ema15:
                breakout=dft.iloc[i]
                break

        if breakout is None: return None

        pct=(ltp-dft.iloc[0]['o'])/dft.iloc[0]['o']*100
        if pct < 0.5 or pct > 20: return None
        if curr['RSI'] < 55: return None
        if curr['v'] < avg10*1.2: return None

        entry=round(breakout['c']+0.05,2)
        sl=round(breakout['l']*0.998,2)
        risk=entry-sl
        if risk/entry > 0.02: sl=round(entry*0.985,2); risk=entry-sl
        if risk<=0: return None

        tgt_50=round(entry+risk*1.25,2)
        tgt_25=round(entry+risk*2.5,2)

        positions[sym]={'entry':entry,'sl':sl,'risk':risk,'tgt_50':tgt_50,'tgt_25':tgt_25,'time':breakout['dt'].strftime("%H:%M"),'booked_50':False,'trail_sl':sl,'r':0,'ltp':ltp}

        return {"type":"BUY","sym":sym,"ltp":ltp,"pct":pct,"entry":entry,"sl":sl,"tgt_50":tgt_50,"tgt_25":tgt_25,"b_time":breakout['dt'].strftime("%H:%M"),"volx":curr['v']/avg10 if avg10>0 else 0,"rsi":curr['RSI']}

    except: return None

def main():
    obj=SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))
    totp=pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET")).now()
    obj.generateSession(os.getenv("ANGEL_CLIENT_ID"),os.getenv("ANGEL_PASSWORD_KEY"),totp)
    scrips=requests.get("https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json").json()
    tmap={s['symbol'].replace('-EQ',''):s['token'] for s in scrips if s['exch_seg']=='NSE' and s['symbol'].endswith('-EQ')}

    positions={}
    if os.path.exists(POS_FILE):
        try: positions=json.load(open(POS_FILE))
        except: positions={}

    print(f"FINAL FAST 9:15-3:30 No YFinance | Scanning {len(SMALLCAP_400)} | Pos {len(positions)}")

    with ThreadPoolExecutor(max_workers=25) as ex:
        res=list(ex.map(lambda s: generate_final_signal((obj,s,tmap,positions)), SMALLCAP_400))

    json.dump(positions, open(POS_FILE,'w'), indent=2)

    # FIX - तो NoneType Error इथे होता - आता Fix!
    valid=[]
    for r in res:
        if r is None: continue
        if not isinstance(r, dict): continue
        if r.get("type"): valid.append(r)

    now=datetime.now(IST).strftime("%d-%b %H:%M")
    if valid:
        msg=f"FINAL 9:15-3:30 No YF {now}\n\n"
        for b in valid:
            if b['type']=='BUY':
                msg+=f"BUY {b['sym']} @ {b['ltp']:.1f} +{b['pct']:.1f}% BO {b['b_time']}\nE {b['entry']} SL {b['sl']}\n50% {b['tgt_50']} FINAL 2.5x {b['tgt_25']}\nVol {b['volx']:.1f}x RSI {b['rsi']:.0f}\n\n"
            else:
                msg+=f"{b['type']} {b['sym']} {b['msg']}\n\n"
    else:
        if positions:
            msg=f"HOLD {len(positions)} Pos | {now} | 3:15 Exit ON\n"
            for s,p in positions.items():
                msg+=f"{s} E {p['entry']} LTP {p.get('ltp',0):.1f} Trail {p.get('trail_sl',p['sl'])} {p.get('r',0):.1f}R\n"
        else:
            msg=f"Scanner OK {now} 9:15-3:30 Active No Signal"

    print(msg)
    bot=os.getenv("TELEGRAM_BOT_TOKEN"); chat=os.getenv("TELEGRAM_CHAT_ID")
    try: requests.get(f"https://api.telegram.org/bot{bot}/sendMessage",params={"chat_id":chat,"text":msg}, timeout=5)
    except: pass

if __name__=="__main__": main()

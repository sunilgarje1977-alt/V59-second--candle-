import numpy as np
import pandas as pd
import yfinance as yf
import ta
from datetime import datetime, time
import pytz
from concurrent.futures import ThreadPoolExecutor

IST = pytz.timezone("Asia/Kolkata")

def calculate_indicators(df):
    """9 EMA, 15 EMA आणि VWAP"""
    if len(df) < 20:
        return df
    df["EMA_9"] = ta.trend.ema_indicator(close=df["Close"], window=9)
    df["EMA_15"] = ta.trend.ema_indicator(close=df["Close"], window=15)
    try:
        df["RSI"] = ta.momentum.rsi(close=df["Close"], window=14)
    except:
        df["RSI"] = 50

    df["Typical_Price"] = (df["High"] + df["Low"] + df["Close"]) / 3
    df["TP_Vol"] = df["Typical_Price"] * df["Volume"]
    df["Date_Group"] = df.index.date
    df["Cum_TP_Vol"] = df.groupby("Date_Group")["TP_Vol"].cumsum()
    df["Cum_Vol"] = df.groupby("Date_Group")["Volume"].cumsum()
    df["VWAP"] = df["Cum_TP_Vol"] / df["Cum_Vol"]
    df["Vol_Avg_10"] = df["Volume"].rolling(10).mean()
    df.drop(columns=["Typical_Price", "TP_Vol", "Date_Group", "Cum_TP_Vol", "Cum_Vol"], inplace=True, errors='ignore')
    return df

def generate_signals_final(df):
    """FINAL 9:15-3:30 + 50% Book + 1:2.5 + Trail + 3:15 Exit"""
    df["Signal"] = "Hold"
    df["Entry_Price"] = np.nan
    df["Stop_Loss"] = np.nan
    df["TGT_50"] = np.nan
    df["TGT_25"] = np.nan
    df["Trail_SL"] = np.nan
    df["Status"] = ""

    position = None

    for i in range(1, len(df)):
        try:
            curr_time = df.index[i].time()
            is_market_hours = time(9,15) <= curr_time <= time(15,30)
            is_exit_time = curr_time >= time(15,15)

            if position and is_exit_time:
                df.iloc[i, df.columns.get_loc("Signal")] = "EXIT 3:15"
                df.iloc[i, df.columns.get_loc("Status")] = f"Final Exit @ {df['Close'].iloc[i]:.1f}"
                position = None
                continue

            if position:
                entry = position['entry']
                risk = position['risk']
                ltp = df['Close'].iloc[i]
                profit_r = (ltp - entry) / risk if risk>0 else 0

                trail_sl = position.get('trail_sl', position['sl'])
                if profit_r >= 1.5:
                    trail_sl = df['Low'].iloc[max(0,i-2):i].min() * 0.998
                elif profit_r >= 1.0:
                    trail_sl = entry

                df.iloc[i, df.columns.get_loc("Trail_SL")] = trail_sl
                position['trail_sl'] = trail_sl

                if profit_r >= 1.25 and not position.get('booked_50'):
                    df.iloc[i, df.columns.get_loc("Signal")] = "50% BOOK"
                    df.iloc[i, df.columns.get_loc("Status")] = f"50% Book @ {ltp:.1f} {profit_r:.1f}R"
                    position['booked_50'] = True

                if ltp <= trail_sl:
                    df.iloc[i, df.columns.get_loc("Signal")] = "SL HIT"
                    position = None
                    continue

                if profit_r >= 2.5:
                    df.iloc[i, df.columns.get_loc("Signal")] = "TGT 2.5x HIT"
                    position = None
                    continue
                continue

            if not is_market_hours: continue

            prev_ema9 = df["EMA_9"].iloc[i-1]
            prev_vwap = df["VWAP"].iloc[i-1]
            curr_ema9 = df["EMA_9"].iloc[i]
            curr_vwap = df["VWAP"].iloc[i]
            curr_ema15 = df["EMA_15"].iloc[i]
            curr_close = df["Close"].iloc[i]

            if pd.isna(prev_ema9) or pd.isna(prev_vwap) or pd.isna(curr_ema9) or pd.isna(curr_vwap):
                continue

            cond = (prev_ema9 <= prev_vwap and curr_ema9 > curr_vwap and curr_close > curr_ema15)

            vol = df["Volume"].iloc[i]
            vol_avg = df["Vol_Avg_10"].iloc[i]
            vol_ok = vol > vol_avg*1.2 if pd.notna(vol_avg) and vol_avg>0 else True

            rsi = df["RSI"].iloc[i]
            rsi_ok = rsi > 55 if pd.notna(rsi) else True

            if cond and vol_ok and rsi_ok:
                entry = curr_close
                sl = df["Low"].iloc[i-1] * 0.998
                risk = entry - sl
                if risk <=0 or risk/entry > 0.02: continue

                tgt_50 = entry + risk*1.25
                tgt_25 = entry + risk*2.5

                df.iloc[i, df.columns.get_loc("Signal")] = "BUY (Strong Breakout)"
                df.iloc[i, df.columns.get_loc("Entry_Price")] = entry
                df.iloc[i, df.columns.get_loc("Stop_Loss")] = sl
                df.iloc[i, df.columns.get_loc("TGT_50")] = tgt_50
                df.iloc[i, df.columns.get_loc("TGT_25")] = tgt_25
                df.iloc[i, df.columns.get_loc("Trail_SL")] = sl
                df.iloc[i, df.columns.get_loc("Status")] = f"E {entry:.1f} SL {sl:.1f} 50% {tgt_50:.1f} 2.5x {tgt_25:.1f}"

                position = {'entry':entry,'sl':sl,'risk':risk,'booked_50':False,'trail_sl':sl}
        except:
            continue
    return df

def scan_one_stock(symbol):
    try:
        # ZOMATO आता ETERNAL झालंय - Fix
        if symbol == "ZOMATO.NS":
            symbol = "ETERNAL.NS"

        data = yf.download(tickers=symbol, period="5d", interval="5m", progress=False, auto_adjust=True)
        if data.empty or len(data) < 30: return None
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        data = calculate_indicators(data)
        data = generate_signals_final(data)

        signals = data[data["Signal"]!= "Hold"].tail(3)
        if not signals.empty:
            last = signals.iloc[-1]
            if pd.notna(last["Signal"]) and last["Signal"]!= "Hold":
                return {
                    "Symbol": symbol.replace(".NS",""),
                    "Signal": str(last["Signal"]),
                    "LTP": round(float(last["Close"]),2),
                    "Entry": round(float(last["Entry_Price"]),2) if pd.notna(last["Entry_Price"]) else 0,
                    "SL": round(float(last["Stop_Loss"]),2) if pd.notna(last["Stop_Loss"]) else 0,
                    "TGT_50": round(float(last["TGT_50"]),2) if pd.notna(last["TGT_50"]) else 0,
                    "TGT_25": round(float(last["TGT_25"]),2) if pd.notna(last["TGT_25"]) else 0,
                    "Status": str(last["Status"]),
                    "Time": str(signals.index[-1].time())[:5]
                }
        return None
    except Exception as e:
        return None

# --- मेन प्रोग्राम - Smallcap 400 ---
if __name__ == "__main__":
    SMALLCAP_400 = [
        "5PAISA.NS","KALYANKJIL.NS","SMCGLOBAL.NS","NUVAMA.NS","NETWEB.NS","PWL.NS","SCI.NS","ESCORTS.NS",
        "MAZDOCK.NS","GRSE.NS","COCHINSHIP.NS","BDL.NS","DATAPATTNS.NS","MTARTECH.NS","IDEA.NS","SUZLON.NS",
        "YESBANK.NS","RPOWER.NS","IRB.NS","ANGELONE.NS","BSE.NS","CDSL.NS","MCX.NS","IRCTC.NS","ETERNAL.NS",
        "PAYTM.NS","BHEL.NS","BEL.NS","HAL.NS","SAIL.NS","VEDL.NS","TATASTEEL.NS","JSWSTEEL.NS","TATAPOWER.NS"
    ]

    print(f"FINAL Scanner 9:15-3:30 | Scanning {len(SMALLCAP_400)} Stocks...")

    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(scan_one_stock, SMALLCAP_400))

    # हाच तो Fix - Bracket चा Error इथे होता!
    valid = []
    for r in results:
        if r is None: continue
        if not isinstance(r, dict): continue
        sig = r.get("Signal", "")
        if not sig: continue
        if "BUY" in sig or "BOOK" in sig or "TGT" in sig or "EXIT" in sig or "SL" in sig:
            valid.append(r)

    if valid:
        df = pd.DataFrame(valid)
        print(f"\n🔥 FINAL SIGNALS 9:15-3:30 (50% Book + 2.5x + Trail + 3:15 Exit):\n")
        print(df[["Symbol","Signal","LTP","Entry","SL","TGT_50","TGT_25","Status","Time"]].to_string(index=False))
    else:
        print("\nआज 9:15-3:30 मध्ये कोणताही Strong Breakout नाही - Scanner OK") 

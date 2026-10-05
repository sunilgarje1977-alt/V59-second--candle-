import numpy as np
import pandas as pd
import yfinance as yf
import ta
from datetime import datetime, time
import pytz
from concurrent.futures import ThreadPoolExecutor

IST = pytz.timezone("Asia/Kolkata")

def calculate_indicators(df):
    """तुझंच Function - 9 EMA, 15 EMA आणि VWAP"""
    df["EMA_9"] = ta.trend.ema_indicator(close=df["Close"], window=9)
    df["EMA_15"] = ta.trend.ema_indicator(close=df["Close"], window=15)
    df["RSI"] = ta.momentum.rsi(close=df["Close"], window=14)

    df["Typical_Price"] = (df["High"] + df["Low"] + df["Close"]) / 3
    df["TP_Vol"] = df["Typical_Price"] * df["Volume"]
    df["Date_Group"] = df.index.date
    df["Cum_TP_Vol"] = df.groupby("Date_Group")["TP_Vol"].cumsum()
    df["Cum_Vol"] = df.groupby("Date_Group")["Volume"].cumsum()
    df["VWAP"] = df["Cum_TP_Vol"] / df["Cum_Vol"]
    df["Vol_Avg_10"] = df["Volume"].rolling(10).mean()

    df.drop(columns=["Typical_Price", "TP_Vol", "Date_Group", "Cum_TP_Vol", "Cum_Vol"], inplace=True)
    return df

def generate_signals_final(df):
    """
    FINAL LOGIC:
    9:15-3:30 Condition Match -> BUY
    SL = Prev Candle Low
    50% Profit Book @ 1.25R
    Final Target @ 2.5R
    Trailing SL -> Candle Low
    3:15 PM Final Exit
    """
    df["Signal"] = "Hold"
    df["Entry_Price"] = np.nan
    df["Stop_Loss"] = np.nan
    df["TGT_50"] = np.nan # 50% Book @ 1.25R
    df["TGT_25"] = np.nan # Final @ 2.5R
    df["Trail_SL"] = np.nan
    df["Status"] = ""

    position = None # Active Trade

    for i in range(1, len(df)):
        curr_time = df.index[i].time()
        # 9:15 to 3:30 Condition - ह्या वेळातच Entry
        is_market_hours = time(9,15) <= curr_time <= time(15,30)
        is_exit_time = curr_time >= time(15,15)

        # 3:15 PM Final Exit
        if position and is_exit_time:
            df.iloc[i, df.columns.get_loc("Signal")] = "EXIT 3:15"
            df.iloc[i, df.columns.get_loc("Status")] = f"Final Exit @ {df['Close'].iloc[i]:.1f}"
            position = None
            continue

        # Position असेल तर Trailing + Targets Check
        if position:
            entry = position['entry']
            sl = position['sl']
            risk = position['risk']
            ltp = df['Close'].iloc[i]
            profit_r = (ltp - entry) / risk if risk>0 else 0

            # Trailing Logic
            if profit_r >= 1.5:
                trail_sl = df['Low'].iloc[i-2:i].min() * 0.998
                df.iloc[i, df.columns.get_loc("Trail_SL")] = trail_sl
                df.iloc[i, df.columns.get_loc("Status")] = f"Trail CandleLow {trail_sl:.1f} {profit_r:.1f}R"
            elif profit_r >= 1.0:
                df.iloc[i, df.columns.get_loc("Trail_SL")] = entry
                df.iloc[i, df.columns.get_loc("Status")] = f"Trail Cost {entry:.1f} {profit_r:.1f}R"

            # 50% Profit Book @ 1.25R
            if profit_r >= 1.25 and not position.get('booked_50'):
                df.iloc[i, df.columns.get_loc("Signal")] = "50% BOOK"
                df.iloc[i, df.columns.get_loc("Status")] = f"50% Book @ {ltp:.1f} {profit_r:.1f}R"
                position['booked_50'] = True

            # SL Hit
            curr_trail = df["Trail_SL"].iloc[i] if pd.notna(df["Trail_SL"].iloc[i]) else sl
            if ltp <= curr_trail:
                df.iloc[i, df.columns.get_loc("Signal")] = "SL HIT"
                position = None
                continue

            # Final Target 2.5R
            if profit_r >= 2.5:
                df.iloc[i, df.columns.get_loc("Signal")] = "TGT 2.5x HIT"
                position = None
                continue

            continue

        # New Entry - तुझा Strong Breakout Rule
        if not is_market_hours: continue

        prev_ema9 = df["EMA_9"].iloc[i-1]
        prev_vwap = df["VWAP"].iloc[i-1]
        curr_ema9 = df["EMA_9"].iloc[i]
        curr_vwap = df["VWAP"].iloc[i]
        curr_ema15 = df["EMA_15"].iloc[i]
        curr_close = df["Close"].iloc[i]
        curr_rsi = df["RSI"].iloc[i]
        vol = df["Volume"].iloc[i]
        vol_avg = df["Vol_Avg_10"].iloc[i]

        # तुझा Condition + Volume + RSI Filter
        cond = (prev_ema9 <= prev_vwap and curr_ema9 > curr_vwap and curr_close > curr_ema15)
        vol_ok = vol > vol_avg*1.2 if pd.notna(vol_avg) else True
        rsi_ok = curr_rsi > 55 if pd.notna(curr_rsi) else True

        if cond and vol_ok and rsi_ok:
            entry = curr_close
            sl = df["Low"].iloc[i-1] * 0.998
            risk = entry - sl
            if risk <=0 or risk/entry > 0.02: continue

            tgt_50 = entry + risk*1.25 # 50% Book
            tgt_25 = entry + risk*2.5 # Final Target

            df.iloc[i, df.columns.get_loc("Signal")] = "BUY (Strong Breakout)"
            df.iloc[i, df.columns.get_loc("Entry_Price")] = entry
            df.iloc[i, df.columns.get_loc("Stop_Loss")] = sl
            df.iloc[i, df.columns.get_loc("TGT_50")] = tgt_50
            df.iloc[i, df.columns.get_loc("TGT_25")] = tgt_25
            df.iloc[i, df.columns.get_loc("Trail_SL")] = sl
            df.iloc[i, df.columns.get_loc("Status")] = f"E {entry:.1f} SL {sl:.1f} 50% {tgt_50:.1f} 2.5x {tgt_25:.1f}"

            position = {'entry':entry,'sl':sl,'risk':risk,'booked_50':False}

    return df

def scan_one_stock(symbol):
    try:
        data = yf.download(tickers=symbol, period="5d", interval="5m", progress=False, auto_adjust=False)
        if data.empty or len(data) < 50: return None
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        data = calculate_indicators(data)
        data = generate_signals_final(data)

        # आजचे Signals
        today_signals = data[data["Signal"]!= "Hold"].tail(5)
        if not today_signals.empty:
            last = today_signals.iloc[-1]
            return {
                "Symbol": symbol.replace(".NS",""),
                "Signal": last["Signal"],
                "LTP": round(last["Close"],2),
                "Entry": round(last["Entry_Price"],2) if pd.notna(last["Entry_Price"]) else 0,
                "SL": round(last["Stop_Loss"],2) if pd.notna(last["Stop_Loss"]) else 0,
                "TGT_50": round(last["TGT_50"],2) if pd.notna(last["TGT_50"]) else 0,
                "TGT_25": round(last["TGT_25"],2) if pd.notna(last["TGT_25"]) else 0,
                "Status": last["Status"],
                "Time": str(today_signals.index[-1].time())[:5]
            }
        return None
    except: return None

# --- मेन प्रोग्राम - Smallcap 400 ---
if __name__ == "__main__":
    # Smallcap 400 List - तू 400 टाकू शकतोस
    SMALLCAP_400 = [
        "5PAISA.NS","KALYANKJIL.NS","SMCGLOBAL.NS","NUVAMA.NS","NETWEB.NS","PWL.NS","SCI.NS","ESCORTS.NS",
        "MAZDOCK.NS","GRSE.NS","COCHINSHIP.NS","BDL.NS","DATAPATTNS.NS","MTARTECH.NS","IDEA.NS","SUZLON.NS",
        "YESBANK.NS","RPOWER.NS","IRB.NS","ANGELONE.NS","BSE.NS","CDSL.NS","MCX.NS","IRCTC.NS","ZOMATO.NS",
        "PAYTM.NS","BHEL.NS","BEL.NS","HAL.NS","MAZDOCK.NS","COCHINSHIP.NS","GRSE.NS","BDL.NS","DATAPATTNS.NS"
        # इथे तू Full 400 ची List टाक
    ]

    print(f"FINAL Scanner 9:15-3:30 | Scanning {len(SMALLCAP_400)} Stocks...")

    # Fast Scan - 10 Stocks एका वेळी
    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(scan_one_stock, SMALLCAP_400))

    valid = [r for r in results if r and "BUY" in r["Signal"] or "BOOK" in r["Signal"] or "TGT" in r["Signal"]]

    if valid:
        df = pd.DataFrame(valid)
        print(f"\n🔥 FINAL SIGNALS 9:15-3:30 (50% Book + 2.5x + Trail + 3:15 Exit):\n")
        print(df[["Symbol","Signal","LTP","Entry","SL","TGT_50","TGT_25","Status","Time"]].to_string(index=False))
    else:
        print("\nआज 9:15-3:30 मध्ये कोणताही Strong Breakout नाही.")

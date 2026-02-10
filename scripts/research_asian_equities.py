#!/usr/bin/env python3
"""Research Asian upstream memory/battery equities."""
import json
import yfinance as yf
import pandas as pd

TICKERS = {
    # Battery upstream - Lithium
    "PLS.AX": {"name": "Pilbara Minerals", "sector": "Battery/Lithium", "exchange": "ASX", "currency": "AUD", "lot_size": 1},
    "1772.HK": {"name": "Ganfeng Lithium", "sector": "Battery/Lithium", "exchange": "HKEX", "currency": "HKD", "lot_size": 500},
    "9696.HK": {"name": "Tianqi Lithium", "sector": "Battery/Lithium", "exchange": "HKEX", "currency": "HKD", "lot_size": 500},
    "MIN.AX": {"name": "Mineral Resources", "sector": "Battery/Lithium", "exchange": "ASX", "currency": "AUD", "lot_size": 1},
    "IGO.AX": {"name": "IGO Limited", "sector": "Battery/Lithium+Nickel", "exchange": "ASX", "currency": "AUD", "lot_size": 1},
    # Battery upstream - Nickel/Cobalt
    "NIC.AX": {"name": "Nickel Industries", "sector": "Battery/Nickel", "exchange": "ASX", "currency": "AUD", "lot_size": 1},
    "3993.HK": {"name": "China Molybdenum", "sector": "Battery/Cobalt+Copper", "exchange": "HKEX", "currency": "HKD", "lot_size": 2000},
    # Battery upstream - Rare Earths
    "LYC.AX": {"name": "Lynas Rare Earths", "sector": "Battery/Rare Earths", "exchange": "ASX", "currency": "AUD", "lot_size": 1},
    # Memory upstream - Silicon/Chemicals
    "3436.T": {"name": "SUMCO Corp", "sector": "Memory/Silicon Wafers", "exchange": "TSE", "currency": "JPY", "lot_size": 100},
    "4063.T": {"name": "Shin-Etsu Chemical", "sector": "Memory/Silicon Wafers", "exchange": "TSE", "currency": "JPY", "lot_size": 100},
    "357780.KS": {"name": "Soulbrain", "sector": "Memory/Semichem", "exchange": "KRX", "currency": "KRW", "lot_size": 1},
    "005290.KS": {"name": "Dongjin Semichem", "sector": "Memory/Semichem", "exchange": "KRX", "currency": "KRW", "lot_size": 1},
    # Korean battery materials
    "003670.KS": {"name": "POSCO Future M", "sector": "Battery/Materials", "exchange": "KRX", "currency": "KRW", "lot_size": 1},
    "247540.KS": {"name": "Ecopro BM", "sector": "Battery/Cathode", "exchange": "KRX", "currency": "KRW", "lot_size": 1},
}

# FX rates
FX_TICKERS = ["AUDUSD=X", "HKDUSD=X", "JPYUSD=X", "KRWUSD=X"]

def get_fx_rates():
    rates = {}
    for fx in FX_TICKERS:
        try:
            t = yf.Ticker(fx)
            h = t.history(period="1d")
            if not h.empty:
                rates[fx.replace("USD=X", "")] = h["Close"].iloc[-1]
        except Exception:
            pass
    # Fallback rates
    rates.setdefault("AUD", 0.63)
    rates.setdefault("HKD", 0.128)
    rates.setdefault("JPY", 0.0066)
    rates.setdefault("KRW", 0.00069)
    return rates

def analyze_ticker(symbol, meta, fx_rates):
    try:
        t = yf.Ticker(symbol)
        info = t.info
        hist_6m = t.history(period="6mo")
        hist_1y = t.history(period="1y")

        if hist_6m.empty:
            return None

        price = hist_6m["Close"].iloc[-1]
        currency = meta["currency"]

        # FX conversion
        fx_key = currency.replace("USD", "")
        if currency == "JPY":
            fx_rate = fx_rates.get("JPY", 0.0066)
        elif currency == "KRW":
            fx_rate = fx_rates.get("KRW", 0.00069)
        elif currency == "AUD":
            fx_rate = fx_rates.get("AUD", 0.63)
        elif currency == "HKD":
            fx_rate = fx_rates.get("HKD", 0.128)
        else:
            fx_rate = 1.0

        price_usd = price * fx_rate
        lot_size = meta["lot_size"]
        min_investment_usd = price_usd * lot_size
        max_shares = int(1000 / (price_usd * lot_size)) * lot_size if price_usd > 0 else 0

        # Technical indicators
        closes = hist_6m["Close"]
        sma_20 = closes.rolling(20).mean().iloc[-1] if len(closes) >= 20 else None
        sma_50 = closes.rolling(50).mean().iloc[-1] if len(closes) >= 50 else None
        sma_200 = hist_1y["Close"].rolling(200).mean().iloc[-1] if len(hist_1y) >= 200 else None

        # RSI 14
        delta = closes.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = (100 - (100 / (1 + rs))).iloc[-1] if len(closes) >= 14 else None

        # Price range
        high_6m = closes.max()
        low_6m = closes.min()
        pct_from_high = ((price - high_6m) / high_6m) * 100
        pct_from_low = ((price - low_6m) / low_6m) * 100

        # Volatility
        daily_returns = closes.pct_change().dropna()
        volatility_annualized = daily_returns.std() * (252 ** 0.5) * 100 if len(daily_returns) > 10 else None

        result = {
            "symbol": symbol,
            "name": meta["name"],
            "sector": meta["sector"],
            "exchange": meta["exchange"],
            "currency": currency,
            "lot_size": lot_size,
            "price_local": round(price, 4),
            "price_usd": round(price_usd, 4),
            "min_investment_usd": round(min_investment_usd, 2),
            "max_shares_1000usd": max_shares,
            "feasible": min_investment_usd <= 1000,
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "pb_ratio": info.get("priceToBook"),
            "dividend_yield": info.get("dividendYield"),
            "ex_dividend_date": str(info.get("exDividendDate", "N/A")),
            "sma_20": round(sma_20, 4) if sma_20 else None,
            "sma_50": round(sma_50, 4) if sma_50 else None,
            "sma_200": round(sma_200, 4) if sma_200 else None,
            "rsi_14": round(rsi, 2) if rsi else None,
            "high_6m": round(high_6m, 4),
            "low_6m": round(low_6m, 4),
            "pct_from_6m_high": round(pct_from_high, 2),
            "pct_from_6m_low": round(pct_from_low, 2),
            "volatility_ann_pct": round(volatility_annualized, 2) if volatility_annualized else None,
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "avg_volume": info.get("averageVolume"),
            "sector_yf": info.get("sector"),
            "industry_yf": info.get("industry"),
            "summary": info.get("longBusinessSummary", "")[:300],
        }
        return result
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

def main():
    print("Fetching FX rates...")
    fx_rates = get_fx_rates()
    print(f"FX rates: {json.dumps({k: round(v, 6) for k, v in fx_rates.items()})}")

    results = []
    for symbol, meta in TICKERS.items():
        print(f"Analyzing {symbol} ({meta['name']})...")
        result = analyze_ticker(symbol, meta, fx_rates)
        if result:
            results.append(result)

    # Sort by feasibility then sector
    feasible = [r for r in results if r.get("feasible")]
    infeasible = [r for r in results if not r.get("feasible")]

    print("\n" + "=" * 120)
    print("FEASIBLE INVESTMENTS (min investment <= USD 1,000)")
    print("=" * 120)
    for r in feasible:
        if "error" in r:
            print(f"\n{r['symbol']}: ERROR - {r['error']}")
            continue
        print(f"\n--- {r['symbol']} | {r['name']} | {r['sector']} | {r['exchange']} ---")
        print(f"  Price: {r['currency']} {r['price_local']} (USD {r['price_usd']})")
        print(f"  Lot size: {r['lot_size']} | Min investment: USD {r['min_investment_usd']} | Max shares w/ $1000: {r['max_shares_1000usd']}")
        print(f"  Market Cap: {r['market_cap']:,.0f}" if r['market_cap'] else "  Market Cap: N/A")
        print(f"  P/E: {r['pe_ratio']} | Fwd P/E: {r['forward_pe']} | P/B: {r['pb_ratio']}")
        print(f"  Div Yield: {r['dividend_yield']:.2%}" if r['dividend_yield'] else "  Div Yield: N/A")
        print(f"  Ex-Div Date: {r['ex_dividend_date']}")
        print(f"  SMA20: {r['sma_20']} | SMA50: {r['sma_50']} | SMA200: {r['sma_200']}")
        print(f"  RSI(14): {r['rsi_14']}")
        print(f"  6M High: {r['high_6m']} | 6M Low: {r['low_6m']}")
        print(f"  From 6M High: {r['pct_from_6m_high']}% | From 6M Low: {r['pct_from_6m_low']}%")
        print(f"  52W High: {r['52w_high']} | 52W Low: {r['52w_low']}")
        print(f"  Annualized Volatility: {r['volatility_ann_pct']}%")
        print(f"  Avg Volume: {r['avg_volume']:,.0f}" if r['avg_volume'] else "  Avg Volume: N/A")
        print(f"  Industry: {r['industry_yf']}")
        print(f"  Summary: {r['summary']}")

    print("\n" + "=" * 120)
    print("INFEASIBLE (min investment > USD 1,000)")
    print("=" * 120)
    for r in infeasible:
        if "error" in r:
            print(f"  {r['symbol']}: ERROR - {r['error']}")
            continue
        print(f"  {r['symbol']} | {r['name']} | Min: USD {r['min_investment_usd']} | Lot: {r['lot_size']} @ {r['currency']} {r['price_local']}")

    # Dump full JSON for further analysis
    with open("/home/jacobw/quantstack/data/equity_research.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull data saved to /home/jacobw/quantstack/data/equity_research.json")

if __name__ == "__main__":
    main()

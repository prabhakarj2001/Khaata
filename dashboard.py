import streamlit as st
import pandas as pd
import yfinance as yf
from price_action_lib import PriceActionAnalyzer

st.title("My Personal Order Block Scanner")

symbol = st.text_input("Enter Stock Symbol (e.g., RELIANCE, TCS):", "RELIANCE")

if st.button("Scan for Order Blocks"):
    with st.spinner("Fetching data..."):
        try:
            # Add .NS for NSE India
            ticker = symbol.upper() + ".NS"
            
            # Fetch last 3 months of daily data
            df = yf.download(ticker, period="3mo", interval="1d", progress=False)
            
            if df.empty:
                st.error(f"Could not find data for {symbol}. Please check the spelling (e.g., RELIANCE, TCS, SBIN).")
            else:
                # yfinance returns MultiIndex columns, we need to flatten them
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                # Clean up column names for the analyzer
                df.rename(columns={
                    'Open': 'open',
                    'High': 'high',
                    'Low': 'low',
                    'Close': 'close',
                    'Volume': 'volume'
                }, inplace=True)

                # Run the Order Block Analyzer
                analyzer = PriceActionAnalyzer()
                result = analyzer.fetch_all(df)

                st.success(f"Analysis Complete for {symbol}!")
                st.write("Here are the most recent days. 'True' means an Order Block was found:")
                st.dataframe(result[['order_block_bullish', 'order_block_bearish']].tail(15))

        except Exception as e:
            st.error(f"Oops, something went wrong: {e}")
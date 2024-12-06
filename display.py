import os
import pandas as pd
import yfinance as yf
import wrds
from dash import Dash, dcc, html, Input, Output
import plotly.express as px

# --- Constants ---
CSV_FILE = "sector_data.csv"
SECTOR_TICKERS = {
    "Technology": ["AAPL", "MSFT", "GOOG", "NVDA", "AMD", "ORCL", "CRM", "ADBE", "INTC", "HPQ"],
    "Healthcare": ["JNJ", "PFE", "MRK", "LLY", "ABT", "TMO", "BMY", "AMGN", "CVS", "GILD"],
    "Energy": ["XOM", "CVX", "BP", "TOT", "COP", "ENB", "EOG", "KMI", "SLB", "OXY"],
    "Finance": ["JPM", "BAC", "C", "WFC", "GS", "MS", "SCHW", "AXP", "USB", "TD"],
    "Consumer Discretionary": ["TSLA", "AMZN", "HD", "MCD", "NKE", "SBUX", "DIS", "BKNG", "LOW", "TGT"],
    "Consumer Staples": ["PG", "KO", "PEP", "WMT", "COST", "MDLZ", "CL", "KHC", "KR", "TAP"],
    "Industrials": ["MMM", "HON", "GE", "BA", "CAT", "RTX", "LMT", "DE", "UPS", "FDX"],
    "Utilities": ["NEE", "DUK", "SO", "AEP", "EXC", "SRE", "D", "PEG", "ED", "XEL"],
    "Real Estate": ["AMT", "PLD", "CCI", "EQIX", "SPG", "PSA", "O", "WELL", "VTR", "HST"],
    "Materials": ["LIN", "APD", "SHW", "ECL", "NUE", "DOW", "DD", "FCX", "ALB", "CE"]
}


def get_or_download_data():
    if os.path.exists(CSV_FILE):
        print(f"Found existing data in {CSV_FILE}.")
        return pd.read_csv(CSV_FILE, parse_dates=["date"])

    print("No data found. Fetching from WRDS...")
    conn = wrds.Connection()

    # Flatten all tickers
    tickers = [ticker for tickers in SECTOR_TICKERS.values() for ticker in tickers]
    tickers_str = ",".join([f"'{ticker}'" for ticker in tickers])

    # Fetch data with date restriction
    query = f"""
    SELECT permno, date, prc AS stock_price, shrout, vol AS volume
    FROM crsp.dsf
    WHERE permno IN (
        SELECT permno
        FROM crsp.msenames
        WHERE ticker IN ({tickers_str})
    )
    AND date >= '2015-01-01'
    """
    data = conn.raw_sql(query)

    # Map permno to tickers
    mapping_query = f"""
    SELECT permno, ticker
    FROM crsp.msenames
    WHERE ticker IN ({tickers_str})
    """
    mapping = conn.raw_sql(mapping_query)
    permno_to_ticker = dict(zip(mapping["permno"], mapping["ticker"]))
    data["ticker"] = data["permno"].map(permno_to_ticker)

    conn.close()

    # Save to CSV
    print(f"Saving data to {CSV_FILE}...")
    data.to_csv(CSV_FILE, index=False)
    return data


def fetch_betas(tickers):
    beta_values = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            beta = stock.info.get("beta", None)
            beta_values[ticker] = beta
        except Exception as e:
            print(f"Could not fetch beta for {ticker}: {e}")
            beta_values[ticker] = None
    return pd.DataFrame.from_dict(beta_values, orient='index', columns=['beta']).reset_index().rename(columns={'index': 'ticker'})

def clean_data(data):
    data = data.drop_duplicates(subset=["ticker", "date"])
    data = data.dropna(subset=["stock_price", "shrout"])
    data["market_cap"] = data["stock_price"] * data["shrout"] * 1000

    tickers = data["ticker"].unique()
    betas = fetch_betas(tickers)
    data = pd.merge(data, betas, on="ticker", how="left")
    return data

# --- Load and Clean Data ---
data = get_or_download_data()
data = clean_data(data)

# --- Dash App ---
app = Dash(__name__)

app.layout = html.Div([
    html.H1("Sector Performance Dashboard", style={'textAlign': 'center'}),

    html.Div([
        html.Label("Select Sector:"),
        dcc.Dropdown(
            id='sector-dropdown',
            options=[{'label': sector, 'value': sector} for sector in SECTOR_TICKERS.keys()],
            value=list(SECTOR_TICKERS.keys())[0]
        ),
        html.Label("Select Tickers:"),
        dcc.Dropdown(
            id='ticker-dropdown',
            options=[],  # Populated dynamically
            multi=True
        )
    ], style={'padding': '20px', 'width': '40%', 'display': 'inline-block'}),

    html.Div([
        html.H3("Sector Averages"),
        html.Div(id='sector-averages', style={'padding': '10px'})
    ]),

    html.Div([
        dcc.Graph(id='sector-trend-graph'),
        dcc.Graph(id='company-comparison-graph')
    ])
])

@app.callback(
    Output('ticker-dropdown', 'options'),
    Input('sector-dropdown', 'value')
)
def update_ticker_dropdown(sector):
    return [{'label': ticker, 'value': ticker} for ticker in SECTOR_TICKERS[sector]]

@app.callback(
    Output('sector-averages', 'children'),
    Output('sector-trend-graph', 'figure'),
    Output('company-comparison-graph', 'figure'),
    Input('sector-dropdown', 'value'),
    Input('ticker-dropdown', 'value')
)
def update_dashboard(sector, selected_tickers):
    sector_tickers = SECTOR_TICKERS[sector]
    sector_data = data[data["ticker"].isin(sector_tickers)]

    avg_market_cap = sector_data["market_cap"].mean()
    avg_stock_price = sector_data["stock_price"].mean()
    avg_beta = sector_data["beta"].mean()

    averages = html.Div([
        html.H4("Sector Averages"),
        html.Ul([
            html.Li(f"Average Market Cap: ${avg_market_cap:,.2f}"),
            html.Li(f"Average Stock Price: ${avg_stock_price:,.2f}"),
            html.Li(f"Average Beta: {avg_beta:.2f}")
        ])
    ])

    if not selected_tickers:
        return averages, {}, {}

    selected_data = sector_data[sector_data["ticker"].isin(selected_tickers)].copy()
    selected_data = selected_data.groupby(['ticker', 'date']).agg({
        'stock_price': 'mean',
        'market_cap': 'mean',
    }).reset_index()

    trend_fig = px.line(
        selected_data,
        x="date",
        y="stock_price",
        color="ticker",
        title="Stock Price Trends"
    )
    trend_fig.update_traces(connectgaps=False)

    comparison_fig = px.bar(
        selected_data.groupby("ticker").mean().reset_index(),
        x="ticker",
        y="market_cap",
        title="Market Cap Comparison"
    )

    beta_list = html.Div([
        html.H4("Selected Ticker Betas"),
        html.Table([
            html.Tr([html.Th("Ticker"), html.Th("Beta")])] +
            [
                html.Tr([html.Td(ticker), html.Td(f"{sector_data[sector_data['ticker'] == ticker]['beta'].iloc[0]:.2f}")])
                for ticker in selected_tickers
            ]
        )
    ])

    combined_info = html.Div([averages, beta_list])
    return combined_info, trend_fig, comparison_fig

if __name__ == '__main__':
    app.run_server(debug=True)

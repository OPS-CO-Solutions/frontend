from flask import Flask, request, jsonify
from sqlalchemy import create_engine, text
import os

app = Flask(__name__)

# Database Connection
DATABASE_URL = os.getenv("DATABASE_URL", "mssql+pyodbc://sa:Database94200%21@banksimdb.eastus.cloudapp.azure.com:1433/financedb?driver=ODBC+Driver+17+for+SQL+Server")
engine = create_engine(DATABASE_URL)

# ----------- Price Endpoints -----------

@app.route("/api/retrieve-price", methods=["GET"])
def retrieve_price():
    symbol = request.args.get("symbol", "").upper()
    if not symbol:
        return jsonify({"error": "Symbol parameter is required"}), 400

    query = text("""
        SELECT Symbol, Price, Name
        FROM market_data.Stock
        WHERE Symbol = :symbol
    """)
    with engine.connect() as conn:
        result = conn.execute(query, {"symbol": symbol}).fetchone()
        if not result:
            return jsonify({"error": "Symbol not found"}), 404

        return jsonify({
            "symbol": result.Symbol,
            "price": float(result.Price),
            "name": result.Name
        })

@app.route("/api/update-price", methods=["PUT"])
def update_price():
    data = request.json
    symbol = request.args.get("symbol", "").upper()
    if not symbol or "price" not in data:
        return jsonify({"error": "Symbol and price required"}), 400

    query = text("""
        UPDATE market_data.Stock
        SET Price = :price
        WHERE Symbol = :symbol
    """)
    with engine.begin() as conn:
        result = conn.execute(query, {"price": data["price"], "symbol": symbol})
        if result.rowcount == 0:
            return jsonify({"error": "Symbol not found"}), 404

    return jsonify({"status": "success", "message": f"Price for {symbol} updated."})

@app.route("/api/delete-price", methods=["DELETE"])
def delete_price():
    symbol = request.args.get("symbol", "").upper()
    if not symbol:
        return jsonify({"error": "Symbol parameter is required"}), 400

    query = text("""
        DELETE FROM market_data.Stock
        WHERE Symbol = :symbol
    """)
    with engine.begin() as conn:
        result = conn.execute(query, {"symbol": symbol})
        if result.rowcount == 0:
            return jsonify({"error": "Symbol not found"}), 404

    return jsonify({"status": "success", "message": f"Price for {symbol} deleted."})

# ----------- Client Valuation -----------

@app.route("/api/client-valuation", methods=["GET"])
def client_valuation():
    query = text("""
        SELECT
            c.ClientCode,
            c.ClientName,
            SUM(pp.Quantity * s.Price) AS TotalValuation
        FROM
            market_data.Client c
        JOIN market_data.portfolio p ON c.ClientCode = p.ClientCode
        JOIN market_data.portfolio_position pp ON p.PortfolioID = pp.PortfolioID
        JOIN market_data.Stock s ON pp.Ticker = s.Symbol
        GROUP BY
            c.ClientCode, c.ClientName
    """)
    with engine.connect() as conn:
        results = conn.execute(query).fetchall()
        valuations = [{
            "ClientCode": row.ClientCode,
            "ClientName": row.ClientName,
            "TotalValuation": float(row.TotalValuation)
        } for row in results]

        return jsonify(valuations)

# ----------- Portfolio CRUD -----------

@app.route("/api/portfolio", methods=["POST"])
def create_portfolio():
    data = request.json
    portfolio_id = data.get("PortfolioID")
    client_code = data.get("ClientCode")
    industry_type = data.get("IndustryType")
    positions = data.get("Positions", [])

    if not (portfolio_id and client_code and industry_type):
        return jsonify({"error": "Missing PortfolioID, ClientCode or IndustryType"}), 400

    insert_portfolio = text("""
        INSERT INTO market_data.portfolio (PortfolioID, ClientCode, IndustryType)
        VALUES (:portfolio_id, :client_code, :industry_type)
    """)

    insert_position = text("""
        INSERT INTO market_data.portfolio_position (PositionID, PortfolioID, Ticker, Quantity)
        VALUES (:position_id, :portfolio_id, :ticker, :quantity)
    """)

    with engine.begin() as conn:
        conn.execute(insert_portfolio, {
            "portfolio_id": portfolio_id,
            "client_code": client_code,
            "industry_type": industry_type
        })

        for idx, pos in enumerate(positions, start=1):
            position_id = f"{portfolio_id}_POS{idx:03d}"
            conn.execute(insert_position, {
                "position_id": position_id,
                "portfolio_id": portfolio_id,
                "ticker": pos["Ticker"].upper(),
                "quantity": pos["Quantity"]
            })

    return jsonify({"status": "success", "message": f"Portfolio {portfolio_id} created."})

@app.route("/api/portfolio/<portfolio_id>", methods=["GET"])
def get_portfolio(portfolio_id):
    query_portfolio = text("""
        SELECT PortfolioID, ClientCode, IndustryType
        FROM market_data.portfolio
        WHERE PortfolioID = :portfolio_id
    """)
    query_positions = text("""
        SELECT PositionID, Ticker, Quantity
        FROM market_data.portfolio_position
        WHERE PortfolioID = :portfolio_id
    """)
    with engine.connect() as conn:
        portfolio = conn.execute(query_portfolio, {"portfolio_id": portfolio_id}).fetchone()
        if not portfolio:
            return jsonify({"error": "Portfolio not found"}), 404

        positions = conn.execute(query_positions, {"portfolio_id": portfolio_id}).fetchall()
        return jsonify({
            "PortfolioID": portfolio.PortfolioID,
            "ClientCode": portfolio.ClientCode,
            "IndustryType": portfolio.IndustryType,
            "Positions": [
                {"PositionID": pos.PositionID, "Ticker": pos.Ticker, "Quantity": pos.Quantity}
                for pos in positions
            ]
        })

@app.route("/api/portfolio/<portfolio_id>", methods=["PUT"])
def update_portfolio(portfolio_id):
    data = request.json
    industry_type = data.get("IndustryType")
    positions = data.get("Positions")

    with engine.begin() as conn:
        if industry_type:
            conn.execute(text("""
                UPDATE market_data.portfolio
                SET IndustryType = :industry_type
                WHERE PortfolioID = :portfolio_id
            """), {"industry_type": industry_type, "portfolio_id": portfolio_id})

        if positions is not None:
            conn.execute(text("""
                DELETE FROM market_data.portfolio_position
                WHERE PortfolioID = :portfolio_id
            """), {"portfolio_id": portfolio_id})

            for idx, pos in enumerate(positions, start=1):
                position_id = f"{portfolio_id}_POS{idx:03d}"
                conn.execute(text("""
                    INSERT INTO market_data.portfolio_position (PositionID, PortfolioID, Ticker, Quantity)
                    VALUES (:position_id, :portfolio_id, :ticker, :quantity)
                """), {
                    "position_id": position_id,
                    "portfolio_id": portfolio_id,
                    "ticker": pos["Ticker"].upper(),
                    "quantity": pos["Quantity"]
                })

    return jsonify({"status": "success", "message": f"Portfolio {portfolio_id} updated."})

@app.route("/api/portfolio/<portfolio_id>", methods=["DELETE"])
def delete_portfolio(portfolio_id):
    with engine.begin() as conn:
        conn.execute(text("""
            DELETE FROM market_data.portfolio_position
            WHERE PortfolioID = :portfolio_id
        """), {"portfolio_id": portfolio_id})

        result = conn.execute(text("""
            DELETE FROM market_data.portfolio
            WHERE PortfolioID = :portfolio_id
        """), {"portfolio_id": portfolio_id})

        if result.rowcount == 0:
            return jsonify({"error": "Portfolio not found"}), 404

    return jsonify({"status": "success", "message": f"Portfolio {portfolio_id} deleted."})

# ----------- Run Flask App -----------
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8000)

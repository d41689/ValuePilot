# ValuePilot

ValuePilot is a financial analysis engine designed to parse Value Line equity reports, extract key metrics, and enable powerful screening and formula-based analysis.

## Prerequisites
- Docker & Docker Compose

## Quick Start

1. **Clone the repository**
2. **Start the stack**
   ```bash
   docker-compose up -d --build
   ```
3. **Access the Application**
   - Frontend: [http://localhost:3000](http://localhost:3000)
   - Backend API Docs: [http://localhost:8001/docs](http://localhost:8001/docs)

## Development

- **Backend Shell**: `docker-compose exec api bash`
- **Run Tests**: `docker-compose exec api pytest`
- **Linting**: `docker-compose exec api ruff check .`

## Key Features (v0.1)
- **PDF Ingestion**: Upload Value Line PDFs.
- **Parsing**: Auto-extract Ticker, Price, P/E, Yield.
- **Normalization**: Converts "1.2 bil", "5%" to numeric values.
- **Screener**: Filter stocks using JSON-based rules.

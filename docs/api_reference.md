# ValuePilot API Reference (v0.1)

Base URL: `/api/v1`

## Authentication
(Not fully implemented in v0.1 Prototype)
- Currently assumes public access or simple user_id query params for prototype.

## Endpoints

### Documents / Ingestion
- **POST** `/documents/upload`
  - **Query Params**: `user_id` (int)
  - **Body**: Multipart Form Data (`file`: PDF)
  - **Description**: Uploads a Value Line PDF, parses it, extracts identity and metrics.
  - **Returns**: Document status and ID.

### Stocks
- **GET** `/stocks/{stock_id}`
  - **Description**: Get stock overview (Ticker, Name).
- **GET** `/stocks/{stock_id}/facts`
  - **Description**: Get active normalized metric facts for a stock.

### Extractions & Traceability
- **GET** `/extractions/document/{document_id}`
  - **Description**: Get raw extraction data for a document, including confidence scores and text snippets.
- **POST** `/extractions/{extraction_id}/correct`
  - **Body**: `{"corrected_value": "..."}`
  - **Description**: Manually correct a specific extraction. Creates a new authoritative manual fact.

### Screener
- **POST** `/screener/run`
  - **Body**: JSON Rule Object
    ```json
    {
      "type": "AND",
      "conditions": [
        {"metric": "pe_ratio", "operator": "<", "value": 20}
      ]
    }
    ```
  - **Description**: Filters active stocks based on current metric facts.

## Users
- **POST** `/users/`
  - **Query Params**: `email`
  - **Description**: Create a new user.

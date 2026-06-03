# SecondKind · Sales Data Cleaner

Internal tool to clean raw Shopify sales CSV exports, preview results,
and push cleaned data to Google Sheets.

---

## Stack

- **Frontend + backend**: Streamlit (Python)
- **Data**: pandas
- **Google Sheets**: gspread + google-auth (service account)
- **Deployment**: Docker (local) → Railway (cloud)

---

## Local setup (Docker — recommended)

```bash
# 1. Clone / copy this folder
cd secondkind-data-tool

# 2. Add your Google credentials (see below for how to get this)
cp /path/to/your/credentials.json ./credentials.json

# 3. Build and run
docker compose up --build

# 4. Open in browser
open http://localhost:8501
```

No Docker? Run directly:

```bash
pip install -r requirements.txt
streamlit run Home.py
```

---

## Google Sheets setup (one-time)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (e.g. "SecondKind Tools")
3. Enable **Google Sheets API** and **Google Drive API**
4. Go to **IAM & Admin → Service Accounts → Create Service Account**
5. Name it (e.g. `secondkind-sheets`), skip optional steps
6. Click the service account → **Keys → Add Key → JSON** → download
7. Save the downloaded file as `credentials.json` in this folder
8. **Share your Google Sheet** with the service account email
   (looks like `secondkind-sheets@your-project.iam.gserviceaccount.com`)
   — give it **Editor** access

---

## Shopify query (use this to generate the raw CSV)

```
FROM sales
  SHOW total_sales, gross_sales, discounts, quantity_ordered
  GROUP BY month, order_name, order_id, customer_id, new_or_returning_customer,
    line_item_is_bundle, subscription_or_one_time, bundle_title, product_title,
    discount_title WITH TOTALS
  TIMESERIES month
  SINCE startOfDay(-365d) UNTIL today
  ORDER BY month ASC
VISUALIZE total_sales TYPE list_with_dimension_values MAX 5
```

Export as CSV, upload to the tool.

---

## Cleaning rules applied

| Rule | Logic |
|------|-------|
| Remove aggregate rows | Rows with no Order name (Shopify monthly totals) |
| Add Shipping label | Product title = empty → labelled "Shipping" |
| Remove Brochures | Product title contains "Brochure" |
| Remove non-clients | Gross Sales > 0 AND Total sales = $0 (free units to influencers/partners) |
| Remove zero net revenue | Total sales = $0 after above filters |

---

## Deploy to Railway (share with client)

1. Push this folder to a private GitHub repo
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Set environment variable:
   - `GOOGLE_CREDENTIALS_JSON` = paste the full contents of your credentials.json
4. Railway auto-detects Dockerfile → builds and deploys
5. Share the Railway URL with the client

Cost: ~$5/month on Railway Starter plan.

---

## File structure

```
secondkind-data-tool/
├── Home.py             # Multipage entry / landing + nav
├── pages/
│   ├── 1_Shopify.py    # Shopify sales cleaner
│   ├── 2_Amazon.py     # Amazon orders cleaner + model push
│   └── 3_freepl.py     # freepl P&L tool
├── brand.py            # Shared brand/styling
├── cleaner.py          # Shopify cleaning logic (isolated, testable)
├── sheets.py           # Google Sheets push
├── freepl.py           # freepl parsing logic
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── credentials.json    # ← you add this (gitignored)
```

> **Never commit credentials.json to git.** Add it to .gitignore.

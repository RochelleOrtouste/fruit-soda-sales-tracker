# Fruit Soda Sales Tracker

A starter sales tracker built with Python, Streamlit, and SQLite.

## Features
- Menu prices: 12 oz ₱29, 16 oz ₱39
- Add-ons: Yakult ₱15, Fruit Jelly Nata ₱5
- Flavors: Green Apple, Strawberry, Lychee
- Automatic order timestamps using Asia/Manila time
- Blank new-order form after saving
- Cash received, change returned, tips, and unclaimed change recorded separately
- Daily sales and expenses
- Capital recovery estimate and estimated cash on hand
- Delete order/expense records
- CSV exports for backup

## Run locally (Windows)
1. Install Python 3.11 or 3.12 from https://www.python.org/downloads/
2. Extract this ZIP.
3. Open Command Prompt in this folder.
4. Run:
   ```bash
   py -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   streamlit run app.py
   ```
5. The app should open in your browser.

## Deploy free with GitHub + Streamlit Community Cloud
1. Create a GitHub repository. For a real business, consider making it private if your plan supports deploying private repositories.
2. Upload `app.py`, `requirements.txt`, and `README.md` to the repository.
3. Sign in at https://share.streamlit.io/ using GitHub.
4. Choose **Create app**, then select your repository, branch, and `app.py`.
5. Deploy.

Official deployment guide: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app

## Important storage note
This starter uses a local SQLite database file (`fruit_soda_tracker.db`). It is suitable for local testing, but cloud-hosted local files may not be durable across restarts/redeployments. Before relying on it for important live business records, connect a persistent hosted database (for example, Supabase/Postgres) or regularly download and safely store the CSV backups. CSV exports are not a full restore/import feature in this starter.

## Accounting assumptions
- Sales do not include tips or unclaimed change.
- Unclaimed change is calculated as cash received − order total − tip − change actually returned, never below zero.
- Cash on hand estimate = opening cash + cash received − change returned − recorded expenses.
- Capital recovery estimate = sales + tips + unclaimed change − recorded expenses, compared with the capital target. This is a simple cash-flow estimate, not formal accounting profit.
- Enter cash received as the actual amount handed over by the customer. Enter only the amount of change you physically returned.

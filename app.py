import sqlite3
from datetime import datetime, date
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st

APP_TITLE = "Fruit Soda Sales Tracker"
DB_PATH = "fruit_soda_tracker.db"
TZ = ZoneInfo("Asia/Manila")

MENU = {
    "12 oz": 29,
    "16 oz": 39,
}
ADDONS = {
    "Yakult": 15,
    "Fruit Jelly Nata": 5,
}
FLAVORS = ["Green Apple", "Strawberry", "Lychee"]

st.set_page_config(page_title=APP_TITLE, page_icon="🥤", layout="wide")

def now_local():
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)

def connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            flavor TEXT NOT NULL,
            cup_size TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            yakult_qty INTEGER NOT NULL DEFAULT 0,
            nata_qty INTEGER NOT NULL DEFAULT 0,
            subtotal REAL NOT NULL,
            cash_received REAL NOT NULL,
            change_returned REAL NOT NULL,
            tip REAL NOT NULL,
            unclaimed_change REAL NOT NULL,
            notes TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spent_at TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL
        );
        """)
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('capital_target','0')")
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('opening_cash','0')")

def get_setting(key, default="0"):
    with connect() as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def set_setting(key, value):
    with connect() as con:
        con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(value)))

def load_orders(start=None, end=None):
    query = "SELECT * FROM orders"
    params = []
    if start and end:
        query += " WHERE date(created_at) BETWEEN ? AND ?"
        params = [start.isoformat(), end.isoformat()]
    query += " ORDER BY created_at DESC, id DESC"
    with connect() as con:
        rows = con.execute(query, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])

def load_expenses(start=None, end=None):
    query = "SELECT * FROM expenses"
    params = []
    if start and end:
        query += " WHERE date(spent_at) BETWEEN ? AND ?"
        params = [start.isoformat(), end.isoformat()]
    query += " ORDER BY spent_at DESC, id DESC"
    with connect() as con:
        rows = con.execute(query, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])

def peso(value):
    return f"₱{float(value):,.2f}"

init_db()
st.title("🥤 Fruit Soda Sales Tracker")
st.caption("Simple order recording, daily sales, expenses, tips, unclaimed change, and capital monitoring.")

with st.sidebar:
    st.header("⚙️ Business Settings")
    current_target = float(get_setting("capital_target", "0"))
    target = st.number_input("Initial capital to recover (₱)", min_value=0.0, value=current_target, step=100.0)
    if st.button("Save capital target", use_container_width=True):
        set_setting("capital_target", target)
        st.success("Capital target saved.")
    opening = float(get_setting("opening_cash", "0"))
    opening_new = st.number_input("Opening cash on hand (₱)", min_value=0.0, value=opening, step=50.0,
                                  help="Cash you already had before starting to use this tracker. Enter once, then leave it unchanged unless you intentionally update it.")
    if st.button("Save opening cash", use_container_width=True):
        set_setting("opening_cash", opening_new)
        st.success("Opening cash saved.")
    st.divider()
    st.caption("Prices are set in the app: 12 oz ₱29, 16 oz ₱39, Yakult ₱15, Fruit Jelly Nata ₱5.")

tab_order, tab_dashboard, tab_expenses, tab_records, tab_backup = st.tabs(
    ["🧾 New Order", "📊 Dashboard", "🧺 Daily Expenses", "📚 Records", "💾 Backup / Restore"]
)

with tab_order:
    st.subheader("New Customer Order")
    st.info("Blank form = no order has been entered yet. Press **Save Order** only after checking the summary.")
    with st.form("new_order_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            order_date = st.date_input(
                "Order date",
                value=now_local().date(),
                max_value=now_local().date()
            )
            flavor = st.selectbox("Flavor", FLAVORS, index=None, placeholder="Choose a flavor")
            cup_size = st.selectbox("Cup size", list(MENU.keys()), index=None, placeholder="Choose a cup size")
            quantity = st.number_input("Number of cups", min_value=1, max_value=200, value=1, step=1)
        with c2:
            yakult_qty = st.number_input("Yakult add-on quantity", min_value=0, max_value=200, value=0, step=1)
            nata_qty = st.number_input("Fruit jelly nata add-on quantity", min_value=0, max_value=200, value=0, step=1)
        st.caption("Add-on quantities are the number of add-on portions. Example: 2 cups with Yakult on both cups = Yakult quantity 2.")
        subtotal = (MENU[cup_size] * quantity if cup_size else 0) + (yakult_qty * ADDONS["Yakult"]) + (nata_qty * ADDONS["Fruit Jelly Nata"])
        st.metric("Order total", peso(subtotal))
        st.markdown("#### Payment")
        p1, p2, p3 = st.columns(3)
        with p1:
            cash_received = st.number_input("Cash received (₱)", min_value=0.0, value=0.0, step=1.0)
        with p2:
            change_returned = st.number_input("Change actually returned (₱)", min_value=0.0, value=0.0, step=1.0)
        with p3:
            tip = st.number_input("Tip (₱)", min_value=0.0, value=0.0, step=1.0)
        notes = st.text_input("Notes (optional)", placeholder="e.g., less ice, customer request")
        save = st.form_submit_button("✅ Save Order", use_container_width=True)

    if save:
        errors = []
        if not flavor or not cup_size:
            errors.append("Please choose both a flavor and a cup size.")
        if subtotal <= 0:
            errors.append("Order total must be greater than zero.")
        if cash_received < subtotal + tip:
            errors.append("Cash received must cover the order total plus any tip entered.")
        if change_returned > max(0, cash_received - subtotal - tip):
            errors.append("Change returned cannot be more than the cash remaining after the order and tip.")
        unclaimed = max(0.0, cash_received - subtotal - tip - change_returned)
        if errors:
            for err in errors:
                st.error(err)
        else:
            created = datetime.combine(order_date, now_local().time())
            with connect() as con:
                con.execute("""INSERT INTO orders
                    (created_at,flavor,cup_size,quantity,yakult_qty,nata_qty,subtotal,cash_received,
                     change_returned,tip,unclaimed_change,notes)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (created.isoformat(sep=" "), flavor, cup_size, int(quantity), int(yakult_qty), int(nata_qty),
                     float(subtotal), float(cash_received), float(change_returned), float(tip), float(unclaimed), notes))
            st.success(f"Order saved! Total: {peso(subtotal)} · Unclaimed change: {peso(unclaimed)}")
            st.caption("The order form clears after saving. Check Records if you need to verify it.")

with tab_dashboard:
    st.subheader("Sales and Cash Overview")
    today = now_local().date()
    selected_date = st.date_input("Choose date", value=today, key="dashboard_date")
    odf = load_orders(selected_date, selected_date)
    edf = load_expenses(selected_date, selected_date)
    sales = float(odf["subtotal"].sum()) if not odf.empty else 0.0
    tips = float(odf["tip"].sum()) if not odf.empty else 0.0
    unclaimed = float(odf["unclaimed_change"].sum()) if not odf.empty else 0.0
    expenses_total = float(edf["amount"].sum()) if not edf.empty else 0.0
    order_cash_in = float((odf["cash_received"] - odf["change_returned"]).sum()) if not odf.empty else 0.0
    all_orders = load_orders()
    all_expenses = load_expenses()
    total_sales = float(all_orders["subtotal"].sum()) if not all_orders.empty else 0.0
    total_tips = float(all_orders["tip"].sum()) if not all_orders.empty else 0.0
    total_unclaimed = float(all_orders["unclaimed_change"].sum()) if not all_orders.empty else 0.0
    total_expenses = float(all_expenses["amount"].sum()) if not all_expenses.empty else 0.0
    opening_cash = float(get_setting("opening_cash", "0"))
    current_cash = opening_cash + float((all_orders["cash_received"] - all_orders["change_returned"]).sum() if not all_orders.empty else 0) - total_expenses
    target = float(get_setting("capital_target", "0"))
    net_toward_capital = total_sales + total_tips + total_unclaimed - total_expenses
    remaining = max(0.0, target - net_toward_capital)

    metrics = st.columns(4)
    metrics[0].metric("Sales today", peso(sales))
    metrics[1].metric("Tips today", peso(tips))
    metrics[2].metric("Unclaimed change today", peso(unclaimed))
    metrics[3].metric("Expenses today", peso(expenses_total))
    st.markdown("#### Daily cash summary")
    st.write(f"**Cash received less change returned today:** {peso(order_cash_in)}")
    st.write(f"**Cash generated today after expenses** (cash received less change returned − expenses): {peso(order_cash_in - expenses_total)}")
    st.caption("Sales exclude tips and unclaimed change. Cash received less change returned includes the order amount, tip, and any unclaimed change.")
    st.divider()
    st.subheader("Overall Capital Monitoring")
    m1, m2, m3 = st.columns(3)
    m1.metric("Current estimated cash on hand", peso(current_cash))
    m2.metric("Net amount toward capital recovery", peso(net_toward_capital))
    m3.metric("Capital still to recover", peso(remaining))
    if target > 0:
        progress = min(1.0, max(0.0, net_toward_capital / target))
        st.progress(progress, text=f"{progress*100:.1f}% of capital target")
    st.warning("Capital recovery is an estimate based on total sales + tips + unclaimed change − recorded expenses. For a more accurate profit report, record ingredient/restocking costs and other business expenses consistently.")

with tab_expenses:
    st.subheader("Record an Expense")
    st.caption("Examples: fruit syrup, soda water, cups, straws, ice, delivery, and other business costs.")
    with st.form("expense_form", clear_on_submit=True):
        e1, e2 = st.columns(2)
        with e1:
            expense_date = st.date_input(
                "Expense date",
                value=now_local().date(),
                max_value=now_local().date()
            )
            category = st.selectbox("Category", ["Ingredients / supplies", "Packaging", "Ice", "Transport / delivery", "Utilities", "Other"])
        with e2:
            description = st.text_input("Description", placeholder="e.g., 1 box of cups")
            amount = st.number_input("Amount (₱)", min_value=0.0, value=0.0, step=10.0)
        expense_save = st.form_submit_button("Save Expense", use_container_width=True)
    if expense_save:
        if not description.strip() or amount <= 0:
            st.error("Please enter a description and an amount greater than zero.")
        else:
            with connect() as con:
                con.execute("INSERT INTO expenses(spent_at,category,description,amount) VALUES(?,?,?,?)",
                            (datetime.combine(expense_date, now_local().time()).isoformat(sep=" "), category, description.strip(), float(amount)))
            st.success("Expense saved.")
    st.divider()
    expense_filter_date = st.date_input("View expenses for date", value=now_local().date(), key="expense_filter")
    eview = load_expenses(expense_filter_date, expense_filter_date)
    if eview.empty:
        st.info("No expenses recorded for this date.")
    else:
        st.dataframe(eview[["id", "spent_at", "category", "description", "amount"]], use_container_width=True, hide_index=True)
        st.write("**Total expenses:**", peso(eview["amount"].sum()))
        delete_expense_id = st.number_input("Expense ID to delete", min_value=0, step=1, value=0)
        if st.button("Delete selected expense", key="delete_expense"):
            if delete_expense_id > 0:
                with connect() as con:
                    cur = con.execute("DELETE FROM expenses WHERE id=?", (int(delete_expense_id),))
                st.success("Expense deleted." if cur.rowcount else "No matching expense ID.")
                st.rerun()

with tab_records:
    st.subheader("Order and Expense Records")
    today = now_local().date()
    d1, d2 = st.columns(2)
    with d1:
        start_date = st.date_input("From", value=today.replace(day=1), key="records_start")
    with d2:
        end_date = st.date_input("To", value=today, key="records_end")
    if start_date > end_date:
        st.error("The start date must be on or before the end date.")
    else:
        records = load_orders(start_date, end_date)
        if records.empty:
            st.info("No orders recorded in this date range.")
        else:
            show_cols = ["id", "created_at", "flavor", "cup_size", "quantity", "yakult_qty", "nata_qty", "subtotal",
                         "cash_received", "change_returned", "tip", "unclaimed_change", "notes"]
            st.dataframe(records[show_cols], use_container_width=True, hide_index=True)
            st.write(f"**Orders:** {len(records)} · **Sales:** {peso(records['subtotal'].sum())}")
            order_id = st.number_input("Order ID to delete", min_value=0, step=1, value=0, key="delete_order_id")
            confirm_delete = st.checkbox("I confirm that I want to permanently delete this order.")
            if st.button("🗑️ Delete order", type="secondary"):
                if order_id <= 0:
                    st.error("Enter a valid Order ID.")
                elif not confirm_delete:
                    st.error("Please check the confirmation box first.")
                else:
                    with connect() as con:
                        cur = con.execute("DELETE FROM orders WHERE id=?", (int(order_id),))
                    st.success("Order deleted." if cur.rowcount else "No matching Order ID.")
                    st.rerun()
        st.divider()
        expenses_range = load_expenses(start_date, end_date)
        st.markdown("#### Expenses in selected date range")
        if expenses_range.empty:
            st.info("No expenses recorded in this date range.")
        else:
            st.dataframe(expenses_range[["id", "spent_at", "category", "description", "amount"]],
                         use_container_width=True, hide_index=True)
            st.write("**Expenses in range:**", peso(expenses_range["amount"].sum()))

with tab_backup:
    st.subheader("Backup and Restore")
    st.warning("Keep regular backups. If you deploy this on a cloud host, local SQLite files may not be durable across restarts/redeployments. For important live sales records, use a persistent hosted database or export backups frequently.")
    all_o = load_orders()
    all_e = load_expenses()
    if not all_o.empty:
        st.download_button("Download orders as CSV", all_o.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"fruit_soda_orders_{now_local().date()}.csv", mime="text/csv")
    else:
        st.caption("No order records available to export yet.")
    if not all_e.empty:
        st.download_button("Download expenses as CSV", all_e.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"fruit_soda_expenses_{now_local().date()}.csv", mime="text/csv")
    else:
        st.caption("No expense records available to export yet.")
    st.markdown("#### How totals are calculated")
    st.markdown("""
    - **Sales:** cup price × quantity + add-on portions.
    - **Tips:** recorded separately from sales.
    - **Unclaimed change:** remaining change not returned to the customer; not counted as sales.
    - **Current estimated cash:** opening cash + (cash received − change returned for all orders) − recorded expenses.
    - **Capital still to recover:** max(0, capital target − (sales + tips + unclaimed change − expenses)).
    """)

st.caption("Time zone: Asia/Manila (Philippines). Keep a backup of your records regularly.")

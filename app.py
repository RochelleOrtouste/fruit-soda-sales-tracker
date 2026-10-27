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

# Inventory quantities are tracked in the units shown. Configure recipe usage
# (especially Sprite and syrup) in the Inventory & Restocking tab.
INVENTORY_DEFAULTS = [
    ("12 oz Cups", "pcs", 0.0, 1.0),
    ("16 oz Cups", "pcs", 0.0, 1.0),
    ("Straws", "pcs", 0.0, 1.0),
    ("Flat Lids", "pcs", 0.0, 1.0),
    ("Green Apple Syrup", "ml", 0.0, 0.0),
    ("Strawberry Syrup", "ml", 0.0, 0.0),
    ("Lychee Syrup", "ml", 0.0, 0.0),
    ("Fruit Jelly Nata", "portions", 0.0, 1.0),
]

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
        CREATE TABLE IF NOT EXISTS inventory_items (
            item_name TEXT PRIMARY KEY,
            unit TEXT NOT NULL,
            stock_qty REAL NOT NULL DEFAULT 0,
            usage_per_cup REAL NOT NULL DEFAULT 0,
            reorder_level REAL NOT NULL DEFAULT 10,
            starting_stock REAL NOT NULL DEFAULT 0,
            stock_purchased REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS inventory_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            moved_at TEXT NOT NULL,
            item_name TEXT NOT NULL,
            quantity_change REAL NOT NULL,
            movement_type TEXT NOT NULL,
            notes TEXT DEFAULT ''
        );
        """)
        # Migrate older databases safely by adding per-item restock thresholds.
        columns = {row[1] for row in con.execute("PRAGMA table_info(inventory_items)").fetchall()}
        if "reorder_level" not in columns:
            con.execute("ALTER TABLE inventory_items ADD COLUMN reorder_level REAL NOT NULL DEFAULT 10")
            default_levels = {
                "12 oz Cups": 10, "16 oz Cups": 10, "Straws": 20, "Flat Lids": 10,
                "Green Apple Syrup": 250, "Strawberry Syrup": 250,
                "Lychee Syrup": 250, "Fruit Jelly Nata": 10,
            }
            for name, level in default_levels.items():
                con.execute("UPDATE inventory_items SET reorder_level=? WHERE item_name=?", (level, name))
        # Add editable starting-stock and purchased-quantity fields to existing databases.
        columns = {row[1] for row in con.execute("PRAGMA table_info(inventory_items)").fetchall()}
        if "starting_stock" not in columns:
            con.execute("ALTER TABLE inventory_items ADD COLUMN starting_stock REAL NOT NULL DEFAULT 0")
            # Preserve the current stock level as the starting count for existing records.
            con.execute("UPDATE inventory_items SET starting_stock=stock_qty")
        if "stock_purchased" not in columns:
            con.execute("ALTER TABLE inventory_items ADD COLUMN stock_purchased REAL NOT NULL DEFAULT 0")
            # Recover restock totals from existing inventory history where available.
            con.execute("""UPDATE inventory_items SET stock_purchased = COALESCE((
                SELECT SUM(quantity_change) FROM inventory_movements
                WHERE inventory_movements.item_name=inventory_items.item_name
                  AND movement_type='Restock' AND quantity_change > 0
            ), 0)""")
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('capital_target','0')")
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('opening_cash','0')")
        default_levels = {
            "12 oz Cups": 10, "16 oz Cups": 10, "Straws": 20, "Flat Lids": 10,
            "Green Apple Syrup": 250, "Strawberry Syrup": 250,
            "Lychee Syrup": 250, "Fruit Jelly Nata": 10,
        }
        for item_name, unit, stock_qty, usage_per_cup in INVENTORY_DEFAULTS:
            con.execute(
                "INSERT OR IGNORE INTO inventory_items(item_name,unit,stock_qty,usage_per_cup,reorder_level) VALUES(?,?,?,?,?)",
                (item_name, unit, stock_qty, usage_per_cup, default_levels.get(item_name, 10))
            )

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

def load_inventory():
    with connect() as con:
        rows = con.execute("SELECT * FROM inventory_items ORDER BY rowid").fetchall()
    return pd.DataFrame([dict(r) for r in rows])

def change_inventory(item_name, quantity_change, movement_type, notes=""):
    """Update stock and record the change in the inventory history."""
    with connect() as con:
        con.execute(
            "UPDATE inventory_items SET stock_qty = stock_qty + ?, "
            "stock_purchased = stock_purchased + CASE WHEN ? = 'Restock' AND ? > 0 THEN ? ELSE 0 END "
            "WHERE item_name = ?",
            (float(quantity_change), movement_type, float(quantity_change), float(quantity_change), item_name)
        )
        con.execute(
            "INSERT INTO inventory_movements(moved_at,item_name,quantity_change,movement_type,notes) VALUES(?,?,?,?,?)",
            (now_local().isoformat(sep=" "), item_name, float(quantity_change), movement_type, notes)
        )

def deduct_order_inventory(cup_size, quantity, flavor, nata_qty):
    """Deduct stock for a newly saved order using configured recipe usage."""
    inventory = load_inventory()
    item_rows = {row["item_name"]: row for _, row in inventory.iterrows()}
    deductions = {
        "12 oz Cups" if cup_size == "12 oz" else "16 oz Cups": float(quantity),
        "Straws": float(quantity),
        "Flat Lids": float(quantity),
        f"{flavor} Syrup": float(quantity) * float(item_rows.get(f"{flavor} Syrup", {}).get("usage_per_cup", 0)),
        "Fruit Jelly Nata": float(nata_qty),
    }
    for item_name, amount in deductions.items():
        if amount > 0 and item_name in item_rows:
            change_inventory(item_name, -amount, "Order usage", f"Order: {quantity} x {cup_size}, {flavor}; nata add-ons: {nata_qty}")

init_db()
st.title("🥤 Fruit Soda Sales Tracker")
st.caption("Order recording, sales, expenses, capital monitoring, and inventory/restocking for ingredients and packaging.")

# Show a persistent in-app warning on every page while the app is open.
_current_inventory = load_inventory()
if not _current_inventory.empty:
    # Restock alerts are only for packaging; Sprite is not tracked by this app.
    _alert_items = ["12 oz Cups", "16 oz Cups", "Straws", "Flat Lids"]
    _items_to_restock = _current_inventory[
        _current_inventory["item_name"].isin(_alert_items)
        & (_current_inventory["stock_qty"].astype(float) <= _current_inventory["reorder_level"].astype(float))
    ]
    if not _items_to_restock.empty:
        st.warning("🛒 RESTOCK REMINDER: " + "; ".join(
            f"{r['item_name']} — {r['stock_qty']:g} {r['unit']} left (restock warning at {r['reorder_level']:g})"
            for _, r in _items_to_restock.iterrows()
        ) + ". Open Inventory & Restocking to review.")

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

tab_order, tab_dashboard, tab_expenses, tab_inventory, tab_records, tab_backup = st.tabs(
    ["🧾 New Order", "📊 Dashboard", "🧺 Daily Expenses", "📦 Inventory & Restocking", "📚 Records", "💾 Backup / Restore"]
)


with tab_order:
    st.subheader("New Customer Order")
    st.info("Check the order summary before pressing Save Order.")

    # Reset the fields after a successful save
    if st.session_state.pop("clear_order_form", False):
        st.session_state["order_date"] = now_local().date()
        st.session_state["order_flavor"] = None
        st.session_state["order_cup_size"] = None
        st.session_state["order_quantity"] = 1
        st.session_state["order_yakult_qty"] = 0
        st.session_state["order_nata_qty"] = 0
        st.session_state["order_cash"] = 0.0
        st.session_state["order_change"] = 0.0
        st.session_state["order_tip"] = 0.0
        st.session_state["order_notes"] = ""

    # Default selections for the clickable controls
    if "order_flavor" not in st.session_state:
        st.session_state["order_flavor"] = None
    if "order_cup_size" not in st.session_state:
        st.session_state["order_cup_size"] = None
    if "order_yakult_qty" not in st.session_state:
        st.session_state["order_yakult_qty"] = 0
    if "order_nata_qty" not in st.session_state:
        st.session_state["order_nata_qty"] = 0

    c1, c2 = st.columns(2)

    with c1:
        order_date = st.date_input(
            "Order date",
            value=now_local().date(),
            max_value=now_local().date(),
            key="order_date"
        )

        st.markdown("### 🍓 Choose Flavor")
        st.caption("All flavors are available in either cup size.")

        flavor_cols = st.columns(3)
        flavor_icons = {
            "Green Apple": "🍏",
            "Strawberry": "🍓",
            "Lychee": "🍈",
        }

        for i, option in enumerate(FLAVORS):
            with flavor_cols[i]:
                selected = st.session_state.get("order_flavor") == option
                if st.button(
                    f"{flavor_icons.get(option, '🥤')}\n{option}",
                    key=f"flavor_choice_{i}",
                    type="primary" if selected else "secondary",
                    use_container_width=True,
                ):
                    st.session_state["order_flavor"] = option
                    st.rerun()

        flavor = st.session_state.get("order_flavor")
        if flavor:
            st.caption(f"Selected flavor: {flavor}")
        else:
            st.info("Tap a flavor to select it.")

        st.markdown("### 🥤 Choose Cup Size")
        cup_cols = st.columns(2)

        with cup_cols[0]:
            selected_12 = st.session_state.get("order_cup_size") == "12 oz"
            if st.button(
                "🥤 12 oz\n₱29",
                key="choose_12oz",
                type="primary" if selected_12 else "secondary",
                use_container_width=True,
            ):
                st.session_state["order_cup_size"] = "12 oz"
                st.rerun()

        with cup_cols[1]:
            selected_16 = st.session_state.get("order_cup_size") == "16 oz"
            if st.button(
                "🥤 16 oz\n₱39",
                key="choose_16oz",
                type="primary" if selected_16 else "secondary",
                use_container_width=True,
            ):
                st.session_state["order_cup_size"] = "16 oz"
                st.rerun()

        cup_size = st.session_state.get("order_cup_size")
        if cup_size:
            st.caption(f"Selected cup size: {cup_size} · {peso(MENU[cup_size])}")
        else:
            st.info("Tap a cup size to select it.")

        quantity = st.number_input(
            "Number of cups",
            min_value=1,
            max_value=200,
            value=1,
            step=1,
            key="order_quantity"
        )

    with c2:
        st.markdown("### ➕ Add-ons")

        # Yakult quantity controls
        st.markdown("**🥛 Yakult — ₱15 each**")
        y_minus, y_count, y_plus = st.columns([1, 2, 1])
        with y_minus:
            if st.button(
                "➖",
                key="yakult_minus",
                disabled=st.session_state.get("order_yakult_qty", 0) <= 0,
                use_container_width=True,
            ):
                st.session_state["order_yakult_qty"] -= 1
                st.rerun()
        with y_count:
            st.metric("Quantity", st.session_state.get("order_yakult_qty", 0))
        with y_plus:
            if st.button(
                "➕",
                key="yakult_plus",
                disabled=st.session_state.get("order_yakult_qty", 0) >= 200,
                use_container_width=True,
            ):
                st.session_state["order_yakult_qty"] += 1
                st.rerun()

        st.divider()

        # Fruit Jelly Nata quantity controls
        st.markdown("**🍓 Fruit Jelly Nata — ₱5 each**")
        n_minus, n_count, n_plus = st.columns([1, 2, 1])
        with n_minus:
            if st.button(
                "➖",
                key="nata_minus",
                disabled=st.session_state.get("order_nata_qty", 0) <= 0,
                use_container_width=True,
            ):
                st.session_state["order_nata_qty"] -= 1
                st.rerun()
        with n_count:
            st.metric("Quantity", st.session_state.get("order_nata_qty", 0))
        with n_plus:
            if st.button(
                "➕",
                key="nata_plus",
                disabled=st.session_state.get("order_nata_qty", 0) >= 200,
                use_container_width=True,
            ):
                st.session_state["order_nata_qty"] += 1
                st.rerun()

        yakult_qty = st.session_state.get("order_yakult_qty", 0)
        nata_qty = st.session_state.get("order_nata_qty", 0)

    st.caption(
        "Add-on quantities are the number of portions. "
        "Example: 2 cups with Yakult on both cups = Yakult quantity 2."
    )

    # Calculate the order total live
    cup_total = MENU[cup_size] * quantity if cup_size else 0
    yakult_total = yakult_qty * ADDONS["Yakult"]
    nata_total = nata_qty * ADDONS["Fruit Jelly Nata"]

    subtotal = cup_total + yakult_total + nata_total

    st.markdown("### Order Summary")

    s1, s2, s3, s4 = st.columns(4)

    s1.metric(
        "Cup total",
        peso(cup_total)
    )

    s2.metric(
        "Yakult",
        peso(yakult_total)
    )

    s3.metric(
        "Fruit Jelly Nata",
        peso(nata_total)
    )

    s4.metric(
        "Order total",
        peso(subtotal)
    )

    # Payment details are simplified: record the order total as collected.
    # Cash received, change returned, and tips are not entered separately.
    cash_received = float(subtotal)
    change_returned = 0.0
    tip = 0.0

    notes = st.text_input(
        "Notes (optional)",
        placeholder="e.g., less ice, customer request",
        key="order_notes"
    )

    save = st.button(
        "✅ Save Order",
        use_container_width=True,
        key="save_order_button"
    )

    if save:
        errors = []

        if not flavor or not cup_size:
            errors.append("Please choose both a flavor and a cup size.")

        if subtotal <= 0:
            errors.append("Order total must be greater than zero.")

        # Payment is recorded as the order total; no separate cash/change/tip fields.
        unclaimed = 0.0

        if errors:
            for err in errors:
                st.error(err)

        else:
            created = datetime.combine(
                order_date,
                now_local().time()
            )

            with connect() as con:
                con.execute(
                    """INSERT INTO orders
                    (created_at, flavor, cup_size, quantity,
                     yakult_qty, nata_qty, subtotal, cash_received,
                     change_returned, tip, unclaimed_change, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        created.isoformat(sep=" "),
                        flavor,
                        cup_size,
                        int(quantity),
                        int(yakult_qty),
                        int(nata_qty),
                        float(subtotal),
                        float(cash_received),
                        float(change_returned),
                        float(tip),
                        float(unclaimed),
                        notes
                    )
                )

            # Deduct stock for this new order. Existing historical orders are not
            # retroactively deducted when inventory tracking is first enabled.
            deduct_order_inventory(cup_size, int(quantity), flavor, int(nata_qty))
            st.session_state["clear_order_form"] = True

            st.success(f"Order saved! Total: {peso(subtotal)}")

            st.rerun()


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
    
    # Number of cups sold for the selected date
    cups_12oz = int(
        odf.loc[odf["cup_size"] == "12 oz", "quantity"].sum()
    ) if not odf.empty else 0

    cups_16oz = int(
        odf.loc[odf["cup_size"] == "16 oz", "quantity"].sum()
    ) if not odf.empty else 0

    total_cups_sold = cups_12oz + cups_16oz

    order_cash_in = float((odf["cash_received"] - odf["change_returned"]).sum()) if not odf.empty else 0.0
    all_orders = load_orders()
    all_expenses = load_expenses()
    total_sales = float(all_orders["subtotal"].sum()) if not all_orders.empty else 0.0
    total_tips = float(all_orders["tip"].sum()) if not all_orders.empty else 0.0
    total_unclaimed_change = float(all_orders["unclaimed_change"].sum()) if not all_orders.empty else 0.0
    total_expenses = float(all_expenses["amount"].sum()) if not all_expenses.empty else 0.0
    opening_cash = float(get_setting("opening_cash", "0"))
    # Customer cash retained includes sales, tips, and unclaimed change, based on
    # cash actually received minus change returned. Do not add sales again to this.
    customer_cash_retained = float(
        (all_orders["cash_received"] - all_orders["change_returned"]).sum()
    ) if not all_orders.empty else 0.0
    current_cash = opening_cash + customer_cash_retained - total_expenses
    target = float(get_setting("capital_target", "0"))
    # Capital still to recover is the initial capital minus current cash on hand.
    # Cash on hand cannot be negative for purposes of this recovery estimate.
    cash_available_for_recovery = max(0.0, current_cash)
    capital_recovered = min(target, cash_available_for_recovery)
    capital_still_to_recover = max(0.0, target - cash_available_for_recovery)

    metrics = st.columns(4)
    metrics[0].metric("Sales today", peso(sales))
    metrics[1].metric("Tips today", peso(tips))
    metrics[2].metric("Unclaimed change today", peso(unclaimed))
    metrics[3].metric("Expenses today", peso(expenses_total))
    
    st.markdown("#### 🥤 Cups Sold")

    cup_metrics = st.columns(3)
    cup_metrics[0].metric("12 oz Cups Sold", cups_12oz)
    cup_metrics[1].metric("16 oz Cups Sold", cups_16oz)
    cup_metrics[2].metric("Total Cups Sold", total_cups_sold)

    st.markdown("#### Daily cash summary")
    st.write(f"**Cash received less change returned today:** {peso(order_cash_in)}")
    st.write(f"**Cash generated today after expenses** (cash received less change returned − expenses): {peso(order_cash_in - expenses_total)}")
    st.caption("Sales exclude tips and unclaimed change. Cash received less change returned includes the order amount, tip, and any unclaimed change.")
    st.divider()
    st.subheader("Overall Capital Monitoring")
    st.markdown("#### All-time sales and cash breakdown")
    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Total sales", peso(total_sales))
    b2.metric("Total tips", peso(total_tips))
    b3.metric("Unclaimed change", peso(total_unclaimed_change))
    b4.metric("Total expenses", peso(total_expenses))

    st.markdown("**How your estimated cash is calculated**")
    st.write(f"Opening cash: **{peso(opening_cash)}**")
    st.write(f"Customer cash retained (cash received − change returned): **{peso(customer_cash_retained)}**")
    st.write(f"Less total recorded expenses: **−{peso(total_expenses)}**")
    st.write(f"**Estimated cash on hand = {peso(opening_cash)} + {peso(customer_cash_retained)} − {peso(total_expenses)} = {peso(current_cash)}**")
    st.caption("Customer cash retained already includes the money collected from sales, tips, and any unclaimed change. Total sales are shown separately for transparency and must not be added to customer cash retained again.")

    # Show all-time expense rows so incorrect entries (such as initial capital
    # accidentally recorded as an expense) can be identified and corrected.
    st.markdown("#### Review all recorded expenses")
    if all_expenses.empty:
        st.info("No expenses have been recorded.")
    else:
        expense_display = all_expenses[["id", "spent_at", "category", "description", "amount"]].copy()
        expense_display["amount"] = expense_display["amount"].apply(peso)
        st.dataframe(expense_display, use_container_width=True, hide_index=True)

        # Initial capital is funding, not an operating expense. Flag a likely
        # data-entry mistake, but never delete/exclude a record automatically.
        capital_like_rows = all_expenses[
            all_expenses["amount"].astype(float).round(2) == round(target, 2)
        ] if target > 0 else pd.DataFrame()
        if not capital_like_rows.empty:
            st.warning(
                f"{len(capital_like_rows)} expense record(s) have an amount equal to your initial capital "
                f"({peso(target)}). If one of these records is your starting capital rather than an actual "
                "purchase, delete that incorrect expense record below. Initial capital should not be recorded as an expense."
            )

        with st.form("delete_all_time_expense_form"):
            # Use readable string options so Streamlit's dropdown search can
            # match the expense ID, date, category, description, or amount.
            expense_options = {}
            for _, expense_row in all_expenses.iterrows():
                expense_id = int(expense_row["id"])
                label = (
                    f"ID {expense_id} — {expense_row['spent_at']} — "
                    f"{expense_row['category']} — {expense_row['description']} — "
                    f"{peso(expense_row['amount'])}"
                )
                expense_options[label] = expense_id
            selected_expense_label = st.selectbox(
                "Select an expense record to delete",
                options=list(expense_options.keys()),
                help="Open the dropdown and type to search by ID, date, category, description, or amount.",
            )
            selected_expense_id = expense_options[selected_expense_label]
            confirm_expense_delete = st.checkbox(
                "I confirm that I want to permanently delete this expense record."
            )
            delete_expense_submit = st.form_submit_button("Delete selected expense record")
        if delete_expense_submit:
            if not confirm_expense_delete:
                st.error("Please confirm before deleting the expense record.")
            else:
                with connect() as con:
                    cur = con.execute("DELETE FROM expenses WHERE id = ?", (int(selected_expense_id),))
                if cur.rowcount:
                    st.success(f"Expense record ID {selected_expense_id} deleted.")
                    st.rerun()
                else:
                    st.error("That expense record could not be found.")

    st.markdown("#### Capital recovery")
    m1, m2, m3 = st.columns(3)
    m1.metric("Initial capital", peso(target))
    m2.metric("Current estimated cash on hand", peso(current_cash))
    m3.metric("Capital still to recover", peso(capital_still_to_recover))
    st.write(
        f"**Calculation:** {peso(target)} initial capital − "
        f"{peso(cash_available_for_recovery)} current cash = "
        f"**{peso(capital_still_to_recover)} still to recover**"
    )
    if target > 0:
        progress = min(1.0, max(0.0, capital_recovered / target))
        st.progress(progress, text=f"{progress*100:.1f}% of initial capital represented by current cash")
    st.caption("This is a cash-based estimate, not a full profit or inventory valuation. It assumes the opening cash setting is correct and all cash transactions and business expenses have been recorded. Initial capital is funding, not an expense; remove it from expenses only if it was entered there by mistake.")

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

with tab_inventory:
    st.subheader("Inventory & Restocking")
    st.caption("Manage the current stock of cups, straws, and flat lids. You can edit the stock count whenever the actual quantity differs—for example, when a customer does not use a flat lid.")

    all_inventory_orders = load_orders()
    all_12oz_sold = int(all_inventory_orders.loc[all_inventory_orders["cup_size"] == "12 oz", "quantity"].sum()) if not all_inventory_orders.empty else 0
    all_16oz_sold = int(all_inventory_orders.loc[all_inventory_orders["cup_size"] == "16 oz", "quantity"].sum()) if not all_inventory_orders.empty else 0
    all_cups_sold = all_12oz_sold + all_16oz_sold
    all_yakult_addons = int(all_inventory_orders["yakult_qty"].sum()) if not all_inventory_orders.empty else 0
    all_nata_addons = int(all_inventory_orders["nata_qty"].sum()) if not all_inventory_orders.empty else 0
    st.markdown("#### All-time sales volume")
    sold_cols = st.columns(5)
    sold_cols[0].metric("Total Cups Sold", all_cups_sold)
    sold_cols[1].metric("12 oz Cups Sold", all_12oz_sold)
    sold_cols[2].metric("16 oz Cups Sold", all_16oz_sold)
    sold_cols[3].metric("Yakult Add-ons", all_yakult_addons)
    sold_cols[4].metric("Fruit Jelly Nata Add-ons", all_nata_addons)

    visible_items = ["12 oz Cups", "16 oz Cups", "Straws", "Flat Lids"]
    inv_all = load_inventory()
    inv = inv_all[inv_all["item_name"].isin(visible_items)].copy()
    st.markdown("#### Stock summary")
    st.caption("Edit Starting Stock, Stock Purchased, Stock Used, or Restock Level. Remaining Stock is calculated as Starting Stock + Stock Purchased − Stock Used. Enter actual usage manually, especially when a customer does not use a flat lid.")
    if inv.empty:
        st.info("No inventory items found.")
    else:
        # Derive editable usage from the inventory equation so manual corrections are supported.
        # Stock Used is editable; Remaining Stock is always calculated from the other quantities.
        stock_editor = pd.DataFrame({
            "Item": inv["item_name"].tolist(),
            "Starting Stock": inv["starting_stock"].astype(float).tolist(),
            "Stock Purchased": inv["stock_purchased"].astype(float).tolist(),
            "Stock Used": [max(0.0, float(r["starting_stock"]) + float(r["stock_purchased"]) - float(r["stock_qty"])) for _, r in inv.iterrows()],
            "Remaining Stock": [max(0.0, float(r["stock_qty"])) for _, r in inv.iterrows()],
            "Restock Level": inv["reorder_level"].astype(float).tolist(),
            "Status": ["RESTOCK" if float(r["stock_qty"]) <= float(r["reorder_level"]) else "In stock" for _, r in inv.iterrows()],
        })
        edited_stock = st.data_editor(
            stock_editor,
            use_container_width=True,
            hide_index=True,
            disabled=["Item", "Remaining Stock", "Status"],
            column_config={
                "Starting Stock": st.column_config.NumberColumn("Starting Stock", min_value=0, step=1),
                "Stock Purchased": st.column_config.NumberColumn("Stock Purchased", min_value=0, step=1, help="Edit to match the actual quantity purchased."),
                "Stock Used": st.column_config.NumberColumn("Stock Used", min_value=0, step=1, help="Enter the actual number used. This can be corrected manually."),
                "Remaining Stock": st.column_config.NumberColumn("Remaining Stock", min_value=0, step=1, help="Calculated as Starting Stock + Stock Purchased − Stock Used."),
                "Restock Level": st.column_config.NumberColumn("Restock Level", min_value=0, step=1),
                "Status": st.column_config.TextColumn("Status"),
            },
            key="editable_packaging_stock_summary"
        )
        # Show the formula result immediately in a preview, before saving.
        preview_stock = edited_stock.copy()
        preview_stock["Remaining Stock"] = (
            preview_stock["Starting Stock"].astype(float)
            + preview_stock["Stock Purchased"].astype(float)
            - preview_stock["Stock Used"].astype(float)
        ).clip(lower=0)
        preview_stock["Status"] = [
            "RESTOCK" if float(row["Remaining Stock"]) <= float(row["Restock Level"]) else "In stock"
            for _, row in preview_stock.iterrows()
        ]
        st.caption("Remaining Stock preview (updates from your edits):")
        st.dataframe(preview_stock[["Item", "Remaining Stock", "Status"]], use_container_width=True, hide_index=True)

        if st.button("Save inventory changes", key="save_packaging_stock_summary"):
            with connect() as con:
                for _, edited_row in edited_stock.iterrows():
                    item_name = edited_row["Item"]
                    old_row = inv.loc[inv["item_name"] == item_name].iloc[0]
                    old_qty = float(old_row["stock_qty"])
                    new_start = max(0.0, float(edited_row["Starting Stock"]))
                    new_purchased = max(0.0, float(edited_row["Stock Purchased"]))
                    new_used = max(0.0, float(edited_row["Stock Used"]))
                    new_qty = max(0.0, new_start + new_purchased - new_used)
                    new_reorder = max(0.0, float(edited_row["Restock Level"]))
                    con.execute("UPDATE inventory_items SET stock_qty=?, starting_stock=?, stock_purchased=?, reorder_level=? WHERE item_name=?",
                                (new_qty, new_start, new_purchased, new_reorder, item_name))
                    if new_qty != old_qty:
                        con.execute(
                            "INSERT INTO inventory_movements(moved_at,item_name,quantity_change,movement_type,notes) VALUES(?,?,?,?,?)",
                            (now_local().isoformat(sep=" "), item_name, new_qty-old_qty, "Stock count adjustment", "Saved starting stock + purchases - manually entered stock used")
                        )
            st.success("Inventory changes saved.")
            st.rerun()

        low_stock = inv[
            (inv["stock_qty"].astype(float) <= inv["reorder_level"].astype(float))
        ]
        if not low_stock.empty:
            st.warning("🛒 RESTOCK WARNING — These items are at or below their restock threshold: " + "; ".join(
                f"{r['item_name']}: {r['stock_qty']:g} {r['unit']} left (warning at {r['reorder_level']:g} {r['unit']})"
                for _, r in low_stock.iterrows()
            ))
        else:
            st.success("Cups, straws, and flat lids are above their restock thresholds.")

    st.divider()
    st.markdown("#### Set restock warning levels")
    st.caption("Choose the minimum quantity that should trigger a warning.")
    with st.form("reorder_levels_form"):
        reorder_values = {}
        reorder_cols = st.columns(2)
        for i, (_, row) in enumerate(inv.iterrows()):
            with reorder_cols[i % 2]:
                reorder_values[row["item_name"]] = st.number_input(
                    f"{row['item_name']} warning level ({row['unit']})",
                    min_value=0.0, value=float(row["reorder_level"]), step=1.0,
                    key=f"reorder_level_{row['item_name']}"
                )
        reorder_submit = st.form_submit_button("Save restock warning levels")
    if reorder_submit:
        with connect() as con:
            for item_name, level in reorder_values.items():
                con.execute("UPDATE inventory_items SET reorder_level=? WHERE item_name=?", (float(level), item_name))
        st.success("Restock warning levels saved.")
        st.rerun()

    st.markdown("#### Record a restock")
    with st.form("restock_inventory_form", clear_on_submit=True):
        restock_item = st.selectbox("Item to restock", visible_items, key="restock_item")
        restock_qty = st.number_input("Quantity added", min_value=0.0, value=0.0, step=1.0, key="restock_qty")
        restock_notes = st.text_input("Notes (optional)", placeholder="e.g., bought 1 pack")
        restock_submit = st.form_submit_button("Add restock")
    if restock_submit:
        if restock_qty <= 0:
            st.error("Enter a restock quantity greater than zero.")
        else:
            change_inventory(restock_item, float(restock_qty), "Restock", restock_notes.strip())
            st.success(f"Added {restock_qty:g} {load_inventory().loc[lambda d: d['item_name'] == restock_item, 'unit'].iloc[0]} to {restock_item}.")
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
    - **Current estimated cash:** opening cash + (cash received − change returned for all orders) − actual recorded business expenses.
    - **Important:** initial capital is funding, not a business expense. Do not enter the initial capital amount in Daily Expenses.
    - **Capital still to recover:** max(0, initial capital target − estimated current cash on hand).
    """)

st.caption("Time zone: Asia/Manila (Philippines). Keep a backup of your records regularly.")

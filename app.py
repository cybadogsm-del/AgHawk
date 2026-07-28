import streamlit as st
import pandas as pd
import sqlite3
from pathlib import Path

st.set_page_config(page_title="Turf Galore Sched", layout="wide")

# --- MAIN MENU SIDEBAR ---
st.sidebar.title("Navigation")
menu_selection = st.sidebar.radio("Main Menu:", [
    "📊 Pipeline Dashboard", 
    "➕ Enter New Order", 
    "👥 Manage Customers", 
    "⚙️ System Settings"
])
st.sidebar.divider()

# --- DATABASE SETUP ---
DB_PATH = Path("turf_orders.db")

def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer TEXT NOT NULL,
            variety TEXT NOT NULL,
            m2_area INTEGER NOT NULL,
            harvest_date TEXT DEFAULT '',
            install_date TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Check if we need to seed initial data
    cursor.execute("SELECT COUNT(*) FROM orders")
    if cursor.fetchone()[0] == 0:
        initial_orders = [
            ("EXCELL GRAY", "Kikuyu", 1800, "2026-06-28", "2026-06-29", "Locked"),
            ("FLEMINGS", "Kikuyu", 1500, "", "", "Pending")
        ]
        cursor.executemany("""
            INSERT INTO orders (customer, variety, m2_area, harvest_date, install_date, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, initial_orders)
        conn.commit()
    conn.close()

def get_all_orders():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM orders ORDER BY created_at DESC", conn)
    conn.close()
    return df

def add_order(customer, variety, m2_area, harvest_date, install_date, status):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO orders (customer, variety, m2_area, harvest_date, install_date, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (customer, variety, m2_area, harvest_date, install_date, status))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id

# Initialize database on app start
init_database()

# --- DYNAMIC LISTS ---
customers = ["EXCELL GRAY", "FLEMINGS", "NEDGE", "GREEN CONCEPTS"]
pallet_options = [60, 70, 80]
varieties = ["Kikuyu", "Santa Anna Couch", "Buffalo"]

# --- ROUTING LOGIC BASED ON MENU ---

if menu_selection == "📊 Pipeline Dashboard":
    st.title("🚜 Turf Galore Sched — Ops Dashboard")
    st.subheader("Master Juggling Pipeline")
    
    df = get_all_orders()
    
    if df.empty:
        st.info("No orders in the system.")
    else:
        def row_color(row):
            if row['harvest_date'] != "" and row['install_date'] != "":
                return ['background-color: #d4edda; color: black'] * len(row)
            return ['background-color: #fff3cd; color: black'] * len(row)
            
        styled_df = df.style.apply(row_color, axis=1)
        selection_event = st.dataframe(
            styled_df, 
            use_container_width=True, 
            hide_index=True, 
            on_select="rerun", 
            selection_mode="single-row"
        )
        
        st.divider()
        selected_row = selection_event.selection.rows
        
        if selected_row:
            selected_data = df.iloc[selected_row[0]]
            st.subheader(f"📝 Edit Order #{selected_data['id']} - {selected_data['customer']}")
            st.success("Perfect! You highlighted a row. Next, we will add the 'Amount Installed' math right here!")
        else:
            st.info("👆 Click on any order row in the table above to view its full details.")

elif menu_selection == "➕ Enter New Order":
    st.title("➕ Queue New Order")
    with st.form("new_order_form"):
        col1, col2 = st.columns(2)
        with col1:
            selected_customer = st.selectbox("Customer Name", customers)
            variety = st.selectbox("Turf Variety", varieties)
            m2_area = st.number_input("Total M2 Area Required", min_value=0, step=10, value=0)
            selected_pallet = st.selectbox("Pallet Capacity Size (M2)", pallet_options)
        with col2:
            tba_dates = st.checkbox("Send to Pending Pipeline (No Dates)", value=True)
            if not tba_dates:
                harvest_date = st.date_input("Confirmed Harvest Date")
                install_date = st.date_input("Confirmed Install Date")
            else:
                harvest_date = None
                install_date = None

        if st.form_submit_button("Add to Schedule"):
            harvest_str = harvest_date.strftime("%Y-%m-%d") if harvest_date else ""
            install_str = install_date.strftime("%Y-%m-%d") if install_date else ""
            status = "Locked" if harvest_date else "Pending"
            
            order_id = add_order(selected_customer, variety, m2_area, harvest_str, install_str, status)
            st.success(f"Added Order #{order_id} successfully!")

elif menu_selection == "👥 Manage Customers":
    st.title("👥 Manage Customers")
    st.info("Customer management tools will go here.")

elif menu_selection == "⚙️ System Settings":
    st.title("⚙️ System Settings")
    st.info("System settings and lists will go here.")

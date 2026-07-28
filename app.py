import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

st.set_page_config(page_title="Turf Galore Sched", layout="wide")

# --- DATABASE SETUP ---
DB_PATH = Path("turf_orders.db")

def init_database():
    """Initialize SQLite database with orders table"""
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
    count = cursor.fetchone()[0]
    
    if count == 0:
        # Insert initial sample data
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
    """Fetch all orders from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, customer, variety, m2_area, harvest_date, install_date, status
        FROM orders ORDER BY created_at DESC
    """)
    
    orders = []
    for row in cursor.fetchall():
        orders.append({
            "id": row[0],
            "customer": row[1],
            "variety": row[2],
            "m2_area": row[3],
            "harvest_date": row[4],
            "install_date": row[5],
            "status": row[6]
        })
    
    conn.close()
    return orders

def add_order(customer, variety, m2_area, harvest_date, install_date, status):
    """Add new order to database"""
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

# --- DYNAMIC LISTS (From Config) ---
customers = ["EXCELL GRAY", "FLEMINGS", "NEDGE", "GREEN CONCEPTS"]
pallet_options = [60, 70, 80]
varieties = ["Kikuyu", "Santa Anna Couch", "Buffalo"]

st.title("🚜 Turf Galore Sched — Ops Dashboard")

# --- 1. THE MASTER PIPELINE (COLOR-CODED) ---
st.subheader("Master Juggling Pipeline")

# Load orders from database
orders = get_all_orders()
df = pd.DataFrame(orders)

def row_color(row):
    # Green if it has dates, Yellow if pending
    if row['harvest_date'] != "" and row['install_date'] != "":
        return ['background-color: #d4edda; color: black'] * len(row)
    else:
        return ['background-color: #fff3cd; color: black'] * len(row)

# Display the color-coded table
if not df.empty:
    styled_df = df.style.apply(row_color, axis=1)
    st.data_editor(styled_df, num_rows="dynamic", use_container_width=True, hide_index=True)
else:
    st.info("No orders in the system.")

st.divider()

# --- 2. ORDER ENTRY FORM ---
st.subheader("Queue New Order")

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
        # Run pallet math
        if m2_area > 0 and selected_pallet > 0:
            full_pallets = int(m2_area // selected_pallet)
            loose_rolls = int(m2_area % selected_pallet)
        else:
            full_pallets, loose_rolls = 0, 0
            
        # Prepare data for database
        harvest_str = harvest_date.strftime("%Y-%m-%d") if harvest_date else ""
        install_str = install_date.strftime("%Y-%m-%d") if install_date else ""
        status = "Locked" if harvest_date else "Pending"
        
        # Add to database
        order_id = add_order(
            selected_customer, variety, m2_area, 
            harvest_str, install_str, status
        )
        
        st.success(f"Added Order #{order_id}! Calculated {full_pallets} full pallets + {loose_rolls} loose rolls.")
        st.rerun()  # Refresh to show new data

# --- 3. DATABASE INFO ---
st.divider()
st.caption(f"📁 Data stored in: {DB_PATH.absolute()}")

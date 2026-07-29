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

# --- DATABASE SETUP (Upgraded to v3 for Customers Table) ---
DB_PATH = Path("turf_orders_v3.db")

def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Create Orders Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer TEXT NOT NULL,
            variety TEXT NOT NULL,
            m2_area INTEGER NOT NULL,
            harvest_date TEXT DEFAULT '',
            install_date TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending',
            amount_installed INTEGER DEFAULT 0,
            remaining_balance INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Create Customers Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)
    
    # Seed initial orders if empty
    cursor.execute("SELECT COUNT(*) FROM orders")
    if cursor.fetchone()[0] == 0:
        initial_orders = [
            ("EXCELL GRAY", "Kikuyu", 1800, "2026-06-28", "2026-06-29", "Locked", 0, 1800),
            ("FLEMINGS", "Kikuyu", 1500, "", "", "Pending", 0, 1500)
        ]
        cursor.executemany("""
            INSERT INTO orders (customer, variety, m2_area, harvest_date, install_date, status, amount_installed, remaining_balance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, initial_orders)
        
    # Seed initial customers if empty
    cursor.execute("SELECT COUNT(*) FROM customers")
    if cursor.fetchone()[0] == 0:
        initial_customers = [("EXCELL GRAY",), ("FLEMINGS",), ("NEDGE",), ("GREEN CONCEPTS",)]
        cursor.executemany("INSERT INTO customers (name) VALUES (?)", initial_customers)

    conn.commit()
    conn.close()

# --- DATABASE HELPER FUNCTIONS ---
def get_all_orders():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM orders ORDER BY created_at DESC", conn)
    conn.close()
    return df

def add_order(customer, variety, m2_area, harvest_date, install_date, status):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO orders (customer, variety, m2_area, harvest_date, install_date, status, amount_installed, remaining_balance)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
    """, (customer, variety, m2_area, harvest_date, install_date, status, m2_area))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id

def get_customer_names():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM customers ORDER BY name ASC")
    # Fetch all names and put them in a simple list
    names = [row[0] for row in cursor.fetchall()]
    conn.close()
    return names

def add_new_customer(name):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # Convert to UPPERCASE to keep data clean
        cursor.execute("INSERT INTO customers (name) VALUES (?)", (name.strip().upper(),))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        # This triggers if the name already exists because we set name to UNIQUE
        return False

# Initialize database on app start
init_database()

# --- DYNAMIC LISTS ---
# Customers are now pulled live from the database!
customers = get_customer_names() 
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
            if row['status'] == 'Installed':
                return ['background-color: #e2e3e5; color: #6c757d'] * len(row)
            elif row['harvest_date'] != "" and row['install_date'] != "":
                return ['background-color: #d4edda; color: black'] * len(row)
            return ['background-color: #fff3cd; color: black'] * len(row)
            
        styled_df = df.style.apply(row_color, axis=1)
        
        selection_event = st.dataframe(
            styled_df, 
            use_container_width=True, 
            hide_index=True, 
            on_select="rerun", 
            selection_mode="single-row",
            column_config={
                "id": "ID",
                "customer": "Customer",
                "variety": "Turf Variety",
                "m2_area": "Total M2",
                "harvest_date": "Harvest",
                "install_date": "Install",
                "status": "Status",
                "amount_installed": "Installed M2",
                "remaining_balance": "Remaining M2",
                "created_at": None
            }
        )
        
        st.divider()
        selected_row = selection_event.selection.rows
        
        if selected_row:
            selected_data = df.iloc[selected_row[0]]
            order_id = int(selected_data['id'])
            
            st.subheader(f"📝 Edit Order #{order_id} - {selected_data['customer']}")
            st.write(f"**Total Area Ordered:** {selected_data['m2_area']} M2")
            
            col1, col2 = st.columns(2)
            with col1:
                current_installed = int(selected_data['amount_installed'])
                new_installed = st.number_input("Total Amount Installed (M2)", min_value=0, value=current_installed, step=10)
            
            with col2:
                auto_remaining = int(selected_data['m2_area']) - new_installed
                new_remaining = st.number_input("Remaining Balance (M2) - Manual Override", value=auto_remaining, step=1)
            
            status_options = ["Pending", "Locked", "Harvested", "Installed", "Cancelled"]
            current_status = selected_data['status']
            if current_status not in status_options:
                current_status = "Pending"
            
            new_status = st.selectbox("Update Status", status_options, index=status_options.index(current_status))

            if st.button("Save Order Updates"):
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE orders 
                    SET amount_installed = ?, remaining_balance = ?, status = ?
                    WHERE id = ?
                """, (new_installed, new_remaining, new_status, order_id))
                conn.commit()
                conn.close()
                st.success("Order updated successfully!")
                st.rerun()
        else:
            st.info("👆 Click on any order row in the table above to view and edit its details.")

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
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Current Customer List")
        # Display the list of customers neatly
        st.dataframe(pd.DataFrame(customers, columns=["Customer Name"]), use_container_width=True, hide_index=True)
        
    with col2:
        st.subheader("➕ Add New Customer")
        with st.form("add_customer_form"):
            new_name = st.text_input("Enter New Customer Name:")
            if st.form_submit_button("Save to Database"):
                if new_name == "":
                    st.error("Please enter a name first.")
                else:
                    success = add_new_customer(new_name)
                    if success:
                        st.success(f"Added {new_name.upper()} to the system!")
                        st.rerun()
                    else:
                        st.error("That customer already exists in the system!")

elif menu_selection == "⚙️ System Settings":
    st.title("⚙️ System Settings")
    st.info("System settings and lists will go here.")

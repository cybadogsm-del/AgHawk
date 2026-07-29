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

# --- DATABASE SETUP (Upgraded to v7 for Pallet Math) ---
DB_PATH = Path("turf_orders_v7.db")

def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Create Orders Table (Now with pallet fields)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer TEXT NOT NULL,
            site_address TEXT DEFAULT '',
            site_contact TEXT DEFAULT '',
            contact_phone TEXT DEFAULT '',
            variety TEXT NOT NULL,
            m2_area INTEGER NOT NULL,
            pallet_size INTEGER DEFAULT 60,
            full_pallets INTEGER DEFAULT 0,
            loose_rolls INTEGER DEFAULT 0,
            harvest_date TEXT DEFAULT '',
            install_date TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending',
            amount_installed INTEGER DEFAULT 0,
            remaining_balance INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Create Customers Table
    cursor.execute("CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
    
    # 3. Create Sites Table
    cursor.execute("CREATE TABLE IF NOT EXISTS sites (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL, site_address TEXT NOT NULL)")
    
    # 4. Create Contacts Table
    cursor.execute("CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY AUTOINCREMENT, site_address TEXT NOT NULL, contact_name TEXT NOT NULL, phone TEXT NOT NULL)")

    # 5. Create Varieties Table
    cursor.execute("CREATE TABLE IF NOT EXISTS varieties (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
    
    # Seed initial data to prevent empty errors
    cursor.execute("SELECT COUNT(*) FROM customers")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO customers (name) VALUES (?)", [("EXCELL GRAY",), ("FLEMINGS",), ("NEDGE",), ("GREEN CONCEPTS",)])
        cursor.execute("INSERT INTO sites (customer_name, site_address) VALUES (?, ?)", ("EXCELL GRAY", "123 Spring St, Melbourne"))
        cursor.execute("INSERT INTO contacts (site_address, contact_name, phone) VALUES (?, ?, ?)", ("123 Spring St, Melbourne", "Dave Foreman", "0412 345 678"))

    # Seed initial varieties
    cursor.execute("SELECT COUNT(*) FROM varieties")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO varieties (name) VALUES (?)", [("Kikuyu",), ("Santa Anna Couch",), ("Buffalo",)])

    conn.commit()
    conn.close()

# --- DATABASE HELPER FUNCTIONS ---
def run_query(query, params=()):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(query, params)
    result = cursor.fetchall()
    conn.commit()
    conn.close()
    return result

def get_customers():
    return [row[0] for row in run_query("SELECT name FROM customers ORDER BY name ASC")]

def get_sites_for_customer(customer_name):
    return [row[0] for row in run_query("SELECT site_address FROM sites WHERE customer_name = ?", (customer_name,))]

def get_contacts_for_site(site_address):
    rows = run_query("SELECT contact_name, phone FROM contacts WHERE site_address = ?", (site_address,))
    return [{"name": r[0], "phone": r[1]} for r in rows]

def get_varieties():
    return [row[0] for row in run_query("SELECT name FROM varieties ORDER BY name ASC")]

def save_new_order(customer, site, contact, phone, variety, m2_area, pallet_size, full_pallets, loose_rolls, harvest, install, status):
    existing_sites = get_sites_for_customer(customer)
    if site not in existing_sites and site.strip() != "":
        run_query("INSERT INTO sites (customer_name, site_address) VALUES (?, ?)", (customer, site))
        
    if site.strip() != "" and contact.strip() != "":
        existing_contacts = [c["name"] for c in get_contacts_for_site(site)]
        if contact not in existing_contacts:
            run_query("INSERT INTO contacts (site_address, contact_name, phone) VALUES (?, ?, ?)", (site, contact, phone))
            
    query = """
        INSERT INTO orders (customer, site_address, site_contact, contact_phone, variety, m2_area, pallet_size, full_pallets, loose_rolls, harvest_date, install_date, status, amount_installed, remaining_balance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
    """
    run_query(query, (customer, site, contact, phone, variety, m2_area, pallet_size, full_pallets, loose_rolls, harvest, install, status, m2_area))

# Initialize database on app start
init_database()

# --- DYNAMIC LISTS ---
pallet_options = [60, 70, 80]
varieties = get_varieties()

# --- ROUTING LOGIC BASED ON MENU ---

if menu_selection == "📊 Pipeline Dashboard":
    st.title("🚜 Turf Galore Sched — Ops Dashboard")
    st.subheader("Master Juggling Pipeline")
    
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM orders ORDER BY created_at DESC", conn)
    conn.close()
    
    if df.empty:
        st.info("No orders in the system.")
    else:
        def row_color(row):
            if row['status'] == 'Installed': return ['background-color: #e2e3e5; color: #6c757d'] * len(row)
            elif row['harvest_date'] != "" and row['install_date'] != "": return ['background-color: #d4edda; color: black'] * len(row)
            return ['background-color: #fff3cd; color: black'] * len(row)
            
        styled_df = df.style.apply(row_color, axis=1)
        
        selection_event = st.dataframe(
            styled_df, 
            use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row",
            column_config={
                "id": "ID", "customer": "Customer", "site_address": "Site", "site_contact": None, 
                "contact_phone": None, "variety": "Variety", "m2_area": "Total M2",
                "pallet_size": None, "full_pallets": "Pallets", "loose_rolls": "Loose Rolls",
                "harvest_date": "Harvest", "install_date": "Install", "status": "Status",
                "amount_installed": "Installed M2", "remaining_balance": "Remaining M2", "created_at": None
            }
        )
        st.divider()
        
        selected_row = selection_event.selection.rows
        if selected_row:
            selected_data = df.iloc[selected_row[0]]
            order_id = int(selected_data['id'])
            st.subheader(f"📝 Edit Order #{order_id}")
            
            new_address = st.text_input("Job Site Address", value=selected_data['site_address'])
            col1, col2 = st.columns(2)
            with col1:
                new_contact = st.text_input("Site Contact", value=selected_data['site_contact'])
                current_installed = int(selected_data['amount_installed'])
                new_installed = st.number_input("Total Installed (M2)", min_value=0, value=current_installed, step=10)
            with col2:
                new_phone = st.text_input("Phone Number", value=selected_data['contact_phone'])
                auto_remaining = int(selected_data['m2_area']) - new_installed
                new_remaining = st.number_input("Remaining Balance (M2)", value=auto_remaining, step=1)
            
            status_options = ["Pending", "Locked", "Harvested", "Installed", "Cancelled"]
            current_status = selected_data['status'] if selected_data['status'] in status_options else "Pending"
            new_status = st.selectbox("Update Status", status_options, index=status_options.index(current_status))

            if st.button("Save Order Updates"):
                run_query("""
                    UPDATE orders SET site_address=?, site_contact=?, contact_phone=?, amount_installed=?, remaining_balance=?, status=? WHERE id=?
                """, (new_address, new_contact, new_phone, new_installed, new_remaining, new_status, order_id))
                st.success("Order updated!")
                st.rerun()

elif menu_selection == "➕ Enter New Order":
    st.title("➕ Queue New Order")
    
    customers = get_customers()
    selected_customer = st.selectbox("1. Select Customer", customers)
    
    existing_sites = get_sites_for_customer(selected_customer)
    site_options = existing_sites + ["➕ Add New Site Address..."]
    selected_site = st.selectbox("2. Select Job Site", site_options)
    
    if selected_site == "➕ Add New Site Address...":
        final_site = st.text_input("Type the New Site Address:")
    else:
        final_site = selected_site
        
    if final_site and final_site.strip() != "":
        existing_contacts = get_contacts_for_site(final_site)
        contact_names = [c["name"] for c in existing_contacts]
        contact_options = contact_names + ["➕ Add New Contact..."]
        selected_contact = st.selectbox("3. Select Site Contact", contact_options)
        
        if selected_contact == "➕ Add New Contact...":
            final_contact = st.text_input("Type the New Contact's Name:")
            final_phone = st.text_input("Type the New Contact's Phone:")
        else:
            final_contact = selected_contact
            matching_phone = next((c["phone"] for c in existing_contacts if c["name"] == final_contact), "")
            final_phone = st.text_input("Contact's Phone", value=matching_phone, disabled=True)
    else:
        final_contact = ""
        final_phone = ""
        
    st.divider()
    st.subheader("Turf Details & Logistics")
    col1, col2 = st.columns(2)
    with col1:
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

    if st.button("Save New Order & Calculate Pallets"):
        if final_site.strip() == "" or final_contact.strip() == "":
            st.error("Please fill in the Site and Contact details!")
        elif m2_area == 0:
            st.error("Please enter a Total M2 Area greater than 0!")
        else:
            # The Magic Pallet Math!
            full_pallets = int(m2_area // selected_pallet)
            loose_rolls = int(m2_area % selected_pallet)
            
            harvest_str = harvest_date.strftime("%Y-%m-%d") if harvest_date else ""
            install_str = install_date.strftime("%Y-%m-%d") if install_date else ""
            status = "Locked" if harvest_date else "Pending"
            
            save_new_order(selected_customer, final_site, final_contact, final_phone, variety, m2_area, selected_pallet, full_pallets, loose_rolls, harvest_str, install_str, status)
            st.success(f"Order saved! 🚜 Calculated: {full_pallets} Full Pallets + {loose_rolls} Loose Rolls.")

elif menu_selection == "👥 Manage Customers":
    st.title("👥 Manage Customers")
    customers = get_customers()
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Current Customer List")
        st.dataframe(pd.DataFrame(customers, columns=["Customer Name"]), use_container_width=True, hide_index=True)
    with col2:
        st.subheader("➕ Add New Customer")
        new_name = st.text_input("Enter New Customer Name:")
        if st.button("Save to Database", key="save_cust"):
            if new_name == "":
                st.error("Please enter a name first.")
            else:
                try:
                    run_query("INSERT INTO customers (name) VALUES (?)", (new_name.strip().upper(),))
                    st.success(f"Added {new_name.upper()}!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("That customer already exists!")

elif menu_selection == "⚙️ System Settings":
    st.title("⚙️ System Settings")
    
    st.subheader("🌱 Manage Turf Varieties")
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("Current Varieties:")
        st.dataframe(pd.DataFrame(varieties, columns=["Variety Name"]), use_container_width=True, hide_index=True)
        
    with col2:
        st.write("➕ Add New Turf Variety")
        new_variety = st.text_input("Enter New Variety Name:")
        if st.button("Save Variety"):
            if new_variety == "":
                st.error("Please enter a variety name first.")
            else:
                try:
                    run_query("INSERT INTO varieties (name) VALUES (?)", (new_variety.strip(),))
                    st.success(f"Added {new_variety} to the system!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("That variety already exists in the system!")

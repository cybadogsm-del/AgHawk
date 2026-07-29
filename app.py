import streamlit as st
import pandas as pd
import sqlite3
import datetime
from pathlib import Path

st.set_page_config(page_title="Turf Galore Sched", layout="wide")

# --- SESSION STATE FOR DRILL-DOWN ---
if "editing_order" not in st.session_state:
    st.session_state.editing_order = None
if "last_menu" not in st.session_state:
    st.session_state.last_menu = None

# --- ROLE SIMULATOR ---
st.sidebar.title("🔐 Access Level")
user_role = st.sidebar.selectbox("Simulate User Role:", [
    "👑 Ops Manager/Admin", 
    "🚜 Farm Staff", 
    "👷 Site Supervisors", 
    "🚚 Linehaul Drivers",
    "🛠️ Installers"
])
st.sidebar.divider()

# --- DYNAMIC MAIN MENU ---
st.sidebar.title("Navigation")
if user_role == "👑 Ops Manager/Admin":
    menu_options = ["📊 Pipeline Dashboard", "📋 Daily Run Sheet", "➕ Enter New Order", "👥 Manage Customers", "⚙️ System Settings"]
else: 
    menu_options = ["📊 Pipeline Dashboard", "📋 Daily Run Sheet"]

menu_selection = st.sidebar.radio("Main Menu:", menu_options)
st.sidebar.divider()

# Reset drill-down if they click a different menu tab
if st.session_state.last_menu != menu_selection:
    st.session_state.editing_order = None
    st.session_state.last_menu = menu_selection

# --- DATABASE SETUP ---
DB_PATH = Path("turf_orders_v11.db")

def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer TEXT NOT NULL,
            purchase_order TEXT DEFAULT '',
            site_address TEXT DEFAULT '',
            site_contact TEXT DEFAULT '',
            contact_phone TEXT DEFAULT '',
            special_instructions TEXT DEFAULT '',
            service_type TEXT DEFAULT '',
            transport_detail TEXT DEFAULT '',
            variety TEXT NOT NULL,
            m2_area INTEGER NOT NULL,
            pallet_size INTEGER DEFAULT 60,
            full_pallets INTEGER DEFAULT 0,
            loose_rolls INTEGER DEFAULT 0,
            harvest_date TEXT DEFAULT '',
            install_date TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending',
            amount_harvested INTEGER DEFAULT 0,
            amount_installed INTEGER DEFAULT 0,
            remaining_balance INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS sites (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL, site_address TEXT NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY AUTOINCREMENT, site_address TEXT NOT NULL, contact_name TEXT NOT NULL, phone TEXT NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS varieties (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS pallet_sizes (id INTEGER PRIMARY KEY AUTOINCREMENT, size INTEGER UNIQUE NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS transport_options (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
    
    cursor.execute("SELECT COUNT(*) FROM customers")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO customers (name) VALUES (?)", [("EXCELL GRAY",), ("FLEMINGS",), ("NEDGE",), ("GREEN CONCEPTS",)])
        cursor.execute("INSERT INTO sites (customer_name, site_address) VALUES (?, ?)", ("EXCELL GRAY", "123 Spring St, Melbourne"))
        cursor.execute("INSERT INTO contacts (site_address, contact_name, phone) VALUES (?, ?, ?)", ("123 Spring St, Melbourne", "Dave Foreman", "0412 345 678"))
        cursor.executemany("INSERT INTO varieties (name) VALUES (?)", [("Kikuyu",), ("Santa Anna Couch",), ("Buffalo",)])
        cursor.executemany("INSERT INTO pallet_sizes (size) VALUES (?)", [(60,), (70,), (80,)])
        cursor.executemany("INSERT INTO transport_options (name) VALUES (?)", [("Fleet Truck #1",), ("Fleet Truck #2",), ("Subbie - John Doe Transport",), ("TBA",)])

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

def get_customers(): return [row[0] for row in run_query("SELECT name FROM customers ORDER BY name ASC")]
def get_sites_for_customer(customer_name): return [row[0] for row in run_query("SELECT site_address FROM sites WHERE customer_name = ?", (customer_name,))]
def get_contacts_for_site(site_address):
    rows = run_query("SELECT contact_name, phone FROM contacts WHERE site_address = ?", (site_address,))
    return [{"name": r[0], "phone": r[1]} for r in rows]
def get_varieties(): return [row[0] for row in run_query("SELECT name FROM varieties ORDER BY name ASC")]
def get_pallet_sizes(): return [row[0] for row in run_query("SELECT size FROM pallet_sizes ORDER BY size ASC")]
def get_transport_options(): return [row[0] for row in run_query("SELECT name FROM transport_options ORDER BY name ASC")]

def save_new_order(customer, po, site, contact, phone, special, service, transport, variety, m2_area, pallet_size, full_pallets, loose_rolls, harvest, install, status):
    existing_sites = get_sites_for_customer(customer)
    if site not in existing_sites and site.strip() != "":
        run_query("INSERT INTO sites (customer_name, site_address) VALUES (?, ?)", (customer, site))
        
    if site.strip() != "" and contact.strip() != "":
        existing_contacts = [c["name"] for c in get_contacts_for_site(site)]
        if contact not in existing_contacts:
            run_query("INSERT INTO contacts (site_address, contact_name, phone) VALUES (?, ?, ?)", (site, contact, phone))
            
    query = """
        INSERT INTO orders (customer, purchase_order, site_address, site_contact, contact_phone, special_instructions, service_type, transport_detail, variety, m2_area, pallet_size, full_pallets, loose_rolls, harvest_date, install_date, status, amount_harvested, amount_installed, remaining_balance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
    """
    run_query(query, (customer, po, site, contact, phone, special, service, transport, variety, m2_area, pallet_size, full_pallets, loose_rolls, harvest, install, status, m2_area))

# Initialize database on app start
init_database()

# --- DYNAMIC LISTS ---
pallet_options = get_pallet_sizes()
varieties = get_varieties()
transport_list = get_transport_options()
service_options = ["Supply Only", "Supply & Deliver", "Supply & Install"]

# --- ROUTING LOGIC BASED ON MENU ---

if menu_selection == "📊 Pipeline Dashboard":
    
    # -------------------------------------------------------------
    # VIEW 1: THE MAIN TABLE
    # -------------------------------------------------------------
    if st.session_state.editing_order is None:
        st.title("🚜 Turf Galore Sched — Ops Dashboard")
        
        col_filter, _ = st.columns([1, 3])
        with col_filter:
            view_mode = st.selectbox("View Filter:", ["Active Pipeline (Pending/Locked/Harvested)", "Completed & Cancelled", "Show All Orders"])
        
        conn = sqlite3.connect(DB_PATH)
        if view_mode == "Active Pipeline (Pending/Locked/Harvested)":
            df = pd.read_sql_query("SELECT * FROM orders WHERE status IN ('Pending', 'Locked', 'Harvested') ORDER BY created_at DESC", conn)
        elif view_mode == "Completed & Cancelled":
            df = pd.read_sql_query("SELECT * FROM orders WHERE status IN ('Installed', 'Cancelled') ORDER BY created_at DESC", conn)
        else:
            df = pd.read_sql_query("SELECT * FROM orders ORDER BY created_at DESC", conn)
        conn.close()
        
        if df.empty:
            st.info("No orders found for this view.")
        else:
            def row_color(row):
                if row['status'] in ['Installed', 'Cancelled']: return ['background-color: #e2e3e5; color: #6c757d'] * len(row)
                elif row['harvest_date'] != "" and row['install_date'] != "": return ['background-color: #d4edda; color: black'] * len(row)
                return ['background-color: #fff3cd; color: black'] * len(row)
                
            styled_df = df.style.apply(row_color, axis=1)
            
            st.markdown("💡 **Click any row to drill down into the order details.**")
            
            # --- THE FIX: We hide 'ID' and shorten the headers to save maximum horizontal space ---
            selection_event = st.dataframe(
                styled_df, 
                use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row",
                column_config={
                    "id": None, # Hiding this claw backs a bunch of pixels!
                    "customer": "Customer", 
                    "purchase_order": None, 
                    "site_address": "Site", 
                    "site_contact": None, 
                    "contact_phone": None, 
                    "special_instructions": None, 
                    "service_type": None, 
                    "transport_detail": None, 
                    "variety": "Turf", # Shortened
                    "m2_area": "Ord",  # Shortened
                    "pallet_size": None, "full_pallets": None, "loose_rolls": None,
                    "harvest_date": "H-Date", # Shortened 
                    "install_date": "I-Date", # Shortened
                    "status": "Status",
                    "amount_harvested": "Harv", # Shortened 
                    "amount_installed": "Inst", # Shortened
                    "remaining_balance": "Bal", # Shortened
                    "created_at": None
                }
            )
            
            if selection_event.selection.rows:
                selected_row = selection_event.selection.rows[0]
                st.session_state.editing_order = int(df.iloc[selected_row]['id'])
                st.rerun()

    # -------------------------------------------------------------
    # VIEW 2: THE DRILL-DOWN BOX
    # -------------------------------------------------------------
    else:
        order_id = st.session_state.editing_order
        
        conn = sqlite3.connect(DB_PATH)
        order_df = pd.read_sql_query(f"SELECT * FROM orders WHERE id = {order_id}", conn)
        conn.close()
        
        if order_df.empty:
            st.error("Order not found.")
            if st.button("⬅️ Back to Pipeline Dashboard"):
                st.session_state.editing_order = None
                st.rerun()
        else:
            selected_data = order_df.iloc[0]
            total_m2 = int(selected_data['m2_area'])
            harv_val = int(selected_data['amount_harvested'])
            inst_val = int(selected_data['amount_installed'])
            rem_val = int(selected_data['remaining_balance'])
            
            if st.button("⬅️ Back to Pipeline Dashboard"):
                st.session_state.editing_order = None
                st.rerun()
                
            st.title(f"🔍 Order #{order_id} Drill-Down: {selected_data['customer']}")
            
            with st.container(border=True):
                po_display = selected_data['purchase_order'] if selected_data['purchase_order'] != "" else "N/A"
                
                s_col1, s_col2, s_col3 = st.columns(3)
                with s_col1:
                    st.markdown(f"**📍 Site Info**\n- **Address:** {selected_data['site_address']}\n- **Contact:** {selected_data['site_contact']}\n- **Phone:** {selected_data['contact_phone']}")
                with s_col2:
                    st.markdown(f"**📋 Logistics**\n- **Cust PO:** {po_display}\n- **Service:** {selected_data['service_type']}\n- **Transport:** {selected_data['transport_detail']}")
                with s_col3:
                    st.markdown(f"**📐 Turf Required**\n- **Total:** {total_m2} M2 ({selected_data['variety']})\n- **Pallets:** {selected_data['pallet_size']} M2\n- **To Cut:** {selected_data['full_pallets']} Full + {selected_data['loose_rolls']} Loose")

                st.write("---")
                
                st.markdown("**📈 Real-Time Order Progress**")
                bar_col1, bar_col2 = st.columns(2)
                with bar_col1:
                    st.caption(f"Harvested: {harv_val} / {total_m2} M2")
                    st.progress(min(harv_val / total_m2, 1.0) if total_m2 > 0 else 0.0)
                with bar_col2:
                    st.caption(f"Installed: {inst_val} / {total_m2} M2 (Balance: {rem_val} M2)")
                    st.progress(min(inst_val / total_m2, 1.0) if total_m2 > 0 else 0.0)

                if selected_data['special_instructions'] != "":
                    st.warning(f"⚠️ **Notes:** {selected_data['special_instructions']}")
                
                st.write("---")
                
                if user_role in ["🚚 Linehaul Drivers", "🛠️ Installers"]:
                    st.error("Read-Only Mode: Your access level only permits viewing the schedule.")
                else:
                    with st.form(key=f"edit_form_{order_id}"):
                        if user_role == "👑 Ops Manager/Admin":
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.markdown("**1. Order Details**")
                                st.text_input("Customer PO", value=selected_data['purchase_order'], key=f"po_{order_id}")
                                st.selectbox("Service", service_options, index=service_options.index(selected_data['service_type']) if selected_data['service_type'] in service_options else 0, key=f"srv_{order_id}")
                                st.selectbox("Transport", transport_list, index=transport_list.index(selected_data['transport_detail']) if selected_data['transport_detail'] in transport_list else 0, key=f"trn_{order_id}")
                            with col2:
                                st.markdown("**2. Progress Update**")
                                st.number_input("Total Harvested (M2)", min_value=0, value=harv_val, step=10, key=f"harv_{order_id}")
                                st.number_input("Total Installed (M2)", min_value=0, value=inst_val, step=10, key=f"inst_{order_id}")
                                st.number_input("Remaining Balance (M2)", value=rem_val, step=1, help="Auto-calculates, but you can override to 0", key=f"rem_{order_id}")
                            with col3:
                                st.markdown("**3. Status & Config**")
                                status_options = ["Pending", "Locked", "Harvested", "Installed", "Cancelled"]
                                st.selectbox("Update Status", status_options, index=status_options.index(selected_data['status']) if selected_data['status'] in status_options else 0, key=f"stat_{order_id}")
                                st.selectbox("Pallet Size", pallet_options, index=pallet_options.index(int(selected_data['pallet_size'])) if int(selected_data['pallet_size']) in pallet_options else 0, key=f"pal_{order_id}")
                                st.text_area("Update Notes", value=selected_data['special_instructions'], key=f"note_{order_id}")
                        
                        elif user_role == "🚜 Farm Staff":
                            st.write("**Farm Staff Edit Mode** (Harvesting & Logistics)")
                            col1, col2 = st.columns(2)
                            with col1:
                                st.number_input("Total Harvested (M2)", min_value=0, value=harv_val, step=10, key=f"harv_{order_id}")
                                st.selectbox("Update Transport", transport_list, index=transport_list.index(selected_data['transport_detail']) if selected_data['transport_detail'] in transport_list else 0, key=f"trn_{order_id}")
                            with col2:
                                st.selectbox("Update Pallet Size", pallet_options, index=pallet_options.index(int(selected_data['pallet_size'])) if int(selected_data['pallet_size']) in pallet_options else 0, key=f"pal_{order_id}")
                                status_options = ["Pending", "Locked", "Harvested"]
                                if selected_data['status'] not in status_options: status_options.append(selected_data['status'])
                                st.selectbox("Update Status", status_options, index=status_options.index(selected_data['status']), key=f"stat_{order_id}")
                        
                        elif user_role == "👷 Site Supervisors":
                            st.write("**Site Supervisor Edit Mode** (Installations)")
                            st.number_input("Total Qty Installed (M2)", min_value=0, value=inst_val, step=10, key=f"inst_{order_id}")
                            st.info("Remaining Balance will automatically calculate when you click Save!")
                            
                            status_options = ["Locked", "Harvested", "Installed"]
                            if selected_data['status'] not in status_options: status_options.append(selected_data['status'])
                            st.selectbox("Update Status", status_options, index=status_options.index(selected_data['status']), key=f"stat_{order_id}")

                        if st.form_submit_button("💾 Save Order Updates"):
                            
                            final_harv = st.session_state.get(f"harv_{order_id}", harv_val)
                            final_inst = st.session_state.get(f"inst_{order_id}", inst_val)
                            final_rem = st.session_state.get(f"rem_{order_id}", rem_val)
                            
                            final_po = st.session_state.get(f"po_{order_id}", selected_data['purchase_order'])
                            final_srv = st.session_state.get(f"srv_{order_id}", selected_data['service_type'])
                            final_trn = st.session_state.get(f"trn_{order_id}", selected_data['transport_detail'])
                            final_stat = st.session_state.get(f"stat_{order_id}", selected_data['status'])
                            final_pal = st.session_state.get(f"pal_{order_id}", int(selected_data['pallet_size']))
                            final_note = st.session_state.get(f"note_{order_id}", selected_data['special_instructions'])
                            
                            if user_role == "👑 Ops Manager/Admin":
                                if final_inst != inst_val and final_rem == rem_val:
                                    final_rem = total_m2 - final_inst
                            elif user_role == "👷 Site Supervisors":
                                final_rem = total_m2 - final_inst
                                
                            full_pallets = int(total_m2 // final_pal)
                            loose_rolls = int(total_m2 % final_pal)
                            
                            run_query("""
                                UPDATE orders SET 
                                purchase_order=?, service_type=?, transport_detail=?, special_instructions=?, amount_harvested=?, amount_installed=?, remaining_balance=?, status=?, pallet_size=?, full_pallets=?, loose_rolls=?
                                WHERE id=?
                            """, (final_po, final_srv, final_trn, final_note, final_harv, final_inst, final_rem, final_stat, final_pal, full_pallets, loose_rolls, order_id))
                            
                            st.session_state.editing_order = None
                            st.toast("✅ Order updated successfully!", icon="✅")
                            st.rerun()

elif menu_selection == "📋 Daily Run Sheet":
    st.title("📋 Daily Run Sheet")
    
    col_date, _ = st.columns([1, 3])
    with col_date:
        target_date = st.date_input("Select Date for Run Sheet", datetime.date.today())
    target_date_str = target_date.strftime("%Y-%m-%d")
    
    conn = sqlite3.connect(DB_PATH)
    harvests = pd.read_sql_query("SELECT customer, purchase_order, service_type, transport_detail, site_address, site_contact, contact_phone, variety, m2_area, full_pallets, loose_rolls, special_instructions, status, amount_harvested, amount_installed FROM orders WHERE harvest_date = ? AND status != 'Cancelled'", conn, params=(target_date_str,))
    installs = pd.read_sql_query("SELECT customer, purchase_order, service_type, transport_detail, site_address, site_contact, contact_phone, variety, m2_area, full_pallets, loose_rolls, special_instructions, status, amount_harvested, amount_installed FROM orders WHERE install_date = ? AND status != 'Cancelled'", conn, params=(target_date_str,))
    conn.close()
    
    clean_columns = {
        "customer": "Customer", "purchase_order": None, "service_type": None, "transport_detail": "Transport",
        "site_address": "Site", "site_contact": "Contact", "contact_phone": None, 
        "variety": "Variety", "m2_area": "M2", "full_pallets": "Pallets", 
        "loose_rolls": "Loose", "special_instructions": "Notes", "status": "Status",
        "amount_harvested": "Harv. M2", "amount_installed": "Inst. M2"
    }

    st.subheader(f"🚜 Harvests for {target_date.strftime('%d %b %Y')}")
    if harvests.empty: st.info("No harvests scheduled for this date.")
    else: st.dataframe(harvests, use_container_width=True, hide_index=True, column_config=clean_columns)
        
    st.divider()
    
    st.subheader(f"🌱 Installs for {target_date.strftime('%d %b %Y')}")
    if installs.empty: st.info("No installs scheduled for this date.")
    else: st.dataframe(installs, use_container_width=True, hide_index=True, column_config=clean_columns)

elif menu_selection == "➕ Enter New Order":
    st.title("➕ Queue New Order")
    
    col_cust, col_po = st.columns(2)
    with col_cust:
        customers = get_customers()
        selected_customer = st.selectbox("1. Select Customer", customers, index=None, placeholder="Choose a Customer...")
    with col_po:
        po_number = st.text_input("Customer Purchase Order (Optional)", placeholder="e.g. PO-99214")
    
    if selected_customer:
        st.divider()
        st.subheader("📍 Job Site Details")
        existing_sites = get_sites_for_customer(selected_customer)
        
        if not existing_sites:
            st.info(f"No previous sites found for {selected_customer}. Enter their first site below.")
            site_mode = "➕ Enter New Site"
        else:
            site_mode = st.radio("Job Site Options:", ["📂 Select Existing Site", "➕ Enter New Site"], horizontal=True)
            
        if site_mode == "📂 Select Existing Site":
            final_site = st.selectbox("Choose Job Site:", existing_sites, index=None, placeholder="Select a saved site...")
        else:
            final_site = st.text_input("Type New Job Site Address:")
            
        if final_site and final_site.strip() != "":
            st.write("---")
            st.subheader("👤 Site Contact")
            existing_contacts = get_contacts_for_site(final_site)
            
            if not existing_contacts:
                st.info("No contacts saved for this site. Enter a new one below.")
                contact_mode = "➕ Enter New Contact"
            else:
                contact_mode = st.radio("Contact Options:", ["📂 Select Existing Contact", "➕ Enter New Contact"], horizontal=True)
                
            if contact_mode == "📂 Select Existing Contact":
                contact_names = [c["name"] for c in existing_contacts]
                selected_contact = st.selectbox("Choose Contact:", contact_names, index=None, placeholder="Select a saved contact...")
                if selected_contact:
                    final_contact = selected_contact
                    matching_phone = next((c["phone"] for c in existing_contacts if c["name"] == final_contact), "")
                    final_phone = st.text_input("Phone Number:", value=matching_phone, disabled=True)
                else:
                    final_contact = ""
                    final_phone = ""
            else:
                col_c1, col_c2 = st.columns(2)
                with col_c1:
                    final_contact = st.text_input("Type New Contact Name:")
                with col_c2:
                    final_phone = st.text_input("Type New Contact Phone:")
        else:
            final_contact = ""
            final_phone = ""
    else:
        final_site = ""
        final_contact = ""
        final_phone = ""
        
    st.divider()
    st.subheader("Turf Details & Logistics")
    col1, col2 = st.columns(2)
    with col1:
        selected_service = st.selectbox("Service Required", service_options, index=None, placeholder="Select Service Type...")
        variety = st.selectbox("Turf Variety", varieties, index=None, placeholder="Select Turf Variety...")
        m2_area = st.number_input("Total M2 Area Required", min_value=10, step=10, value=None, placeholder="Enter total area...")
        
    with col2:
        selected_transport = st.selectbox("Transport / Fleet", transport_list, index=None, placeholder="Select Transport Details...")
        selected_pallet = st.selectbox("Pallet Capacity Size (M2)", pallet_options, index=None, placeholder="Select Pallet Size...")
        tba_dates = st.checkbox("Send to Pending Pipeline (No Dates)", value=True)
        if not tba_dates:
            harvest_date = st.date_input("Confirmed Harvest Date", value=None)
            install_date = st.date_input("Confirmed Install Date", value=None)
        else:
            harvest_date = None
            install_date = None

    special_instructions = st.text_area("Special Instructions (Optional)", placeholder="e.g., Gate code is 1234, call Dave before arriving...")

    if st.button("Save New Order & Calculate Pallets"):
        if not selected_customer: st.error("Please select a Customer!")
        elif final_site.strip() == "" or final_contact.strip() == "": st.error("Please fill in the Site and Contact details!")
        elif not selected_service: st.error("Please select a Service Required!")
        elif not variety: st.error("Please select a Turf Variety!")
        elif not selected_transport: st.error("Please select Transport Details! (Select 'TBA' if unknown)")
        elif not m2_area: st.error("Please enter a Total M2 Area!")
        elif not selected_pallet: st.error("Please select a Pallet Size!")
        elif not tba_dates and (not harvest_date or not install_date): st.error("Please select both Harvest and Install dates!")
        else:
            full_pallets = int(m2_area // selected_pallet)
            loose_rolls = int(m2_area % selected_pallet)
            
            harvest_str = harvest_date.strftime("%Y-%m-%d") if harvest_date else ""
            install_str = install_date.strftime("%Y-%m-%d") if install_date else ""
            status = "Locked" if harvest_date else "Pending"
            
            save_new_order(selected_customer, po_number, final_site, final_contact, final_phone, special_instructions, selected_service, selected_transport, variety, m2_area, selected_pallet, full_pallets, loose_rolls, harvest_str, install_str, status)
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
            if new_name == "": st.error("Please enter a name first.")
            else:
                try:
                    run_query("INSERT INTO customers (name) VALUES (?)", (new_name.strip().upper(),))
                    st.success(f"Added {new_name.upper()}!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("That customer already exists!")
        
        st.divider()
        with st.expander("🗑️ Delete a Customer"):
            del_cust = st.selectbox("Select Customer to Remove:", customers)
            if st.button("Delete Customer"):
                run_query("DELETE FROM customers WHERE name = ?", (del_cust,))
                st.success(f"Deleted {del_cust}")
                st.rerun()

elif menu_selection == "⚙️ System Settings":
    st.title("⚙️ System Settings")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.subheader("🌱 Turf Varieties")
        st.dataframe(pd.DataFrame(varieties, columns=["Variety Name"]), use_container_width=True, hide_index=True)
        
        new_variety = st.text_input("Add Turf Variety:")
        if st.button("Save Variety"):
            if new_variety != "":
                try:
                    run_query("INSERT INTO varieties (name) VALUES (?)", (new_variety.strip(),))
                    st.success("Variety Added!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Variety exists!")
                    
        with st.expander("🗑️ Delete Variety"):
            del_var = st.selectbox("Select to delete:", varieties, key="del_var_sel")
            if st.button("Delete", key="del_var_btn"):
                run_query("DELETE FROM varieties WHERE name = ?", (del_var,))
                st.rerun()
                    
    with col2:
        st.subheader("🪵 Pallet Sizes")
        st.dataframe(pd.DataFrame(pallet_options, columns=["Pallet Size (M2)"]), use_container_width=True, hide_index=True)
        
        new_pallet = st.number_input("Add Pallet Size:", min_value=1, step=1, value=50)
        if st.button("Save Pallet Size"):
            try:
                run_query("INSERT INTO pallet_sizes (size) VALUES (?)", (int(new_pallet),))
                st.success("Size Added!")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("Size exists!")
                
        with st.expander("🗑️ Delete Pallet Size"):
            del_pal = st.selectbox("Select to delete:", pallet_options, key="del_pal_sel")
            if st.button("Delete", key="del_pal_btn"):
                run_query("DELETE FROM pallet_sizes WHERE size = ?", (int(del_pal),))
                st.rerun()
                
    with col3:
        st.subheader("🚚 Transport Options")
        st.dataframe(pd.DataFrame(transport_list, columns=["Fleet / Subbie Name"]), use_container_width=True, hide_index=True)
        
        new_transport = st.text_input("Add Fleet # or Subcontractor:")
        if st.button("Save Transport"):
            if new_transport != "":
                try:
                    run_query("INSERT INTO transport_options (name) VALUES (?)", (new_transport.strip(),))
                    st.success("Transport Added!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Transport exists!")

        with st.expander("🗑️ Delete Transport"):
            del_trans = st.selectbox("Select to delete:", transport_list, key="del_trans_sel")
            if st.button("Delete", key="del_trans_btn"):
                run_query("DELETE FROM transport_options WHERE name = ?", (del_trans,))
                st.rerun()

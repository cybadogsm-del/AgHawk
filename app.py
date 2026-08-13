import streamlit as st
import sqlite3
import pandas as pd
import json
import hashlib
import time
from datetime import datetime, timedelta

# ==========================================
# 1. GLOBAL CONFIG & DATABASE INITIALIZATION
# ==========================================
st.set_page_config(page_title="AgHawk", layout="wide")

def get_db_connection():
    return sqlite3.connect('aghawk.db', check_same_thread=False)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, pin_code TEXT, 
        is_active INTEGER DEFAULT 1, role TEXT DEFAULT 'operator', 
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP, is_family_farm INTEGER DEFAULT 0)''')
    
    # Land Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS land (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, size_sqm REAL, is_irrigated INTEGER)''')
    
    # Equipment Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS equipment (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, category TEXT, 
        hourly_cost REAL, fuel_burn_rate REAL, has_ute_toggle INTEGER, custom_fields TEXT)''')
    
    # Audit Log (SHA-256 Hashed)
    cursor.execute('''CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
        user_id INTEGER, action TEXT, previous_hash TEXT, current_hash TEXT)''')
    
    # Works Orders Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS works_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, equipment_id INTEGER, land_id INTEGER, 
        ute_included INTEGER, hours REAL, gps_lat TEXT, gps_long TEXT, status TEXT)''')
    
    # Sales Orders Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS sales_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, customer TEXT, entity_type TEXT, 
        turf_type TEXT, qty REAL, final_price REAL, date TEXT)''')
    
    # Seed Admin User if empty
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO users (name, pin_code, role, is_family_farm) VALUES ('Master Admin', '0000', 'admin', 0)")
        
    # Seed Genesis Hash if empty
    cursor.execute("SELECT COUNT(*) FROM audit_log")
    if cursor.fetchone()[0] == 0:
        genesis_hash = hashlib.sha256(b"AGHAWK_GENESIS").hexdigest()
        cursor.execute("INSERT INTO audit_log (user_id, action, current_hash) VALUES (0, 'SYSTEM_INIT', ?)", (genesis_hash,))
        
    conn.commit()
    conn.close()

# ==========================================
# 2. CRYPTOGRAPHIC HASHING & TRUTH ENGINE
# ==========================================
def log_audit(user_id, action_payload):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT current_hash FROM audit_log ORDER BY id DESC LIMIT 1")
    prev_hash = cursor.fetchone()[0]
    
    timestamp = str(datetime.now())
    raw_string = f"{prev_hash}{timestamp}{user_id}{action_payload}"
    new_hash = hashlib.sha256(raw_string.encode('utf-8')).hexdigest()
    
    cursor.execute("INSERT INTO audit_log (user_id, action, previous_hash, current_hash) VALUES (?, ?, ?, ?)",
                   (user_id, action_payload, prev_hash, new_hash))
    conn.commit()
    conn.close()

# ==========================================
# 3. AUTHENTICATION & PAYWALL LOGIC
# ==========================================
def check_paywall(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT created_at, is_family_farm, is_active FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if not user: return False
    created_at = datetime.strptime(user[0], '%Y-%m-%d %H:%M:%S')
    is_family_farm, is_active = user[1], user[2]
    
    if is_active == 0:
        return False
    if is_family_farm == 1:
        return True # Family farms never blocked automatically
    if datetime.now() > created_at + timedelta(days=7) and st.session_state.role != 'admin':
        return False # 7-day trial expired for corporate
    return True

init_db()

if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'show_splash' not in st.session_state: st.session_state.show_splash = True

if st.session_state.show_splash:
    st.markdown("<h1 style='text-align: center; margin-top: 30vh;'>🦅 AgHawk System Initializing...</h1>", unsafe_allow_html=True)
    time.sleep(1.5)
    st.session_state.show_splash = False
    st.rerun()

if not st.session_state.logged_in:
    st.title("AgHawk Secure Login")
    pin = st.text_input("Enter 4-Digit PIN", type="password", max_chars=4)
    if st.button("Login"):
        conn = get_db_connection()
        user = conn.execute("SELECT id, name, role FROM users WHERE pin_code = ?", (pin,)).fetchone()
        conn.close()
        
        if user:
            if not check_paywall(user[0]):
                st.error("Access Restricted. Subscription Trial Expired or Account Inactive.")
            else:
                st.session_state.update({'logged_in': True, 'user_id': user[0], 'user_name': user[1], 'role': user[2]})
                st.rerun()
        else:
            st.error("Invalid PIN.")
    st.stop()

# ==========================================
# 4. APP ROUTING & UI SHELL
# ==========================================
st.sidebar.title(f"Welcome, {st.session_state.user_name}")
if st.sidebar.button("Logout"):
    st.session_state.clear()
    st.rerun()

if st.sidebar.button("Unsubscribe / Deactivate", type="primary"):
    conn = get_db_connection()
    conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (st.session_state.user_id,))
    conn.commit()
    conn.close()
    st.session_state.clear()
    st.rerun()

menu = st.sidebar.radio("Navigation", ["Dashboard", "Ag Portal (The Dirt)", "Works Orders", "Sales & Logistics", "AI Reports"])

# ==========================================
# 5. MODULE: AG PORTAL (LAND & EQUIPMENT)
# ==========================================
if menu == "Ag Portal (The Dirt)":
    st.header("Agricultural Portal")
    tab1, tab2 = st.tabs(["Land Management", "Equipment & Fleet"])
    conn = get_db_connection()
    
    with tab1:
        st.subheader("Add Paddock")
        with st.container(border=True):
            name = st.text_input("Paddock Name")
            size = st.number_input("Size (Sq Meters)", min_value=0.0)
            irrigated = st.checkbox("Irrigated?")
            if st.button("Save Land"):
                conn.execute("INSERT INTO land (name, size_sqm, is_irrigated) VALUES (?, ?, ?)", (name, int(irrigated)))
                conn.commit()
                log_audit(st.session_state.user_id, f"CREATED_LAND: {name}")
                st.success("Saved.")
                time.sleep(0.5); st.rerun()
        st.dataframe(pd.read_sql_query("SELECT * FROM land", conn), use_container_width=True)

    with tab2:
        st.subheader("Add Equipment")
        with st.container(border=True):
            eq_name = st.text_input("Asset Name")
            cat_opts = ["Tractor", "Harvester", "Implement", "Light Vehicle", "Create New Field..."]
            eq_cat = st.selectbox("Category", cat_opts)
            if eq_cat == "Create New Field...": eq_cat = st.text_input("Enter Custom Category")
            
            hr_cost = st.number_input("Hourly Cost ($)", min_value=0.0)
            ute_tog = st.checkbox("Enable Support Vehicle (Ute) Travel Toggle")
            
            st.markdown("**Custom Attributes (JSON)**")
            c_key = st.text_input("Attribute Name (e.g., Pallet Capacity)")
            c_val = st.text_input("Attribute Value")
            
            if st.button("Save Equipment"):
                c_json = json.dumps({c_key: c_val}) if c_key else "{}"
                conn.execute("INSERT INTO equipment (name, category, hourly_cost, has_ute_toggle, custom_fields) VALUES (?, ?, ?, ?, ?)", 
                             (eq_name, eq_cat, hr_cost, int(ute_tog), c_json))
                conn.commit()
                log_audit(st.session_state.user_id, f"CREATED_EQ: {eq_name}")
                st.success("Saved.")
                time.sleep(0.5); st.rerun()
        st.dataframe(pd.read_sql_query("SELECT * FROM equipment", conn), use_container_width=True)
    conn.close()

# ==========================================
# 6. MODULE: WORKS ORDERS (TRUTH ENGINE)
# ==========================================
elif menu == "Works Orders":
    st.header("Field Operations")
    conn = get_db_connection()
    land_df = pd.read_sql_query("SELECT id, name FROM land", conn)
    eq_df = pd.read_sql_query("SELECT id, name, has_ute_toggle FROM equipment", conn)
    
    with st.container(border=True):
        st.subheader("Start New Job")
        land_sel = st.selectbox("Select Paddock", land_df['name'].tolist() if not land_df.empty else ["No Paddocks"])
        eq_sel = st.selectbox("Select Equipment", eq_df['name'].tolist() if not eq_df.empty else ["No Equipment"])
        
        # Ute Toggle Logic
        show_ute = False
        if not eq_df.empty:
            sel_eq_row = eq_df[eq_df['name'] == eq_sel]
            if not sel_eq_row.empty and sel_eq_row.iloc[0]['has_ute_toggle'] == 1:
                show_ute = True
                
        ute_included = st.checkbox("Include Support Vehicle (Ute) Costs") if show_ute else False
        hours = st.number_input("Hours Worked", min_value=0.0, step=0.5)
        
        # Truth Engine Check
        st.markdown("**Truth Verification**")
        gps_lat = st.text_input("GPS Latitude (Auto-filled on device)")
        gps_long = st.text_input("GPS Longitude")
        
        if st.button("Log Job & Hash to Ledger"):
            if land_sel != "No Paddocks" and eq_sel != "No Equipment" and gps_lat and gps_long:
                l_id = int(land_df[land_df['name'] == land_sel].iloc[0]['id'])
                e_id = int(eq_df[eq_df['name'] == eq_sel].iloc[0]['id'])
                
                conn.execute("INSERT INTO works_orders (date, equipment_id, land_id, ute_included, hours, gps_lat, gps_long, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (str(datetime.now().date()), e_id, l_id, int(ute_included), hours, gps_lat, gps_long, "CLOSED"))
                conn.commit()
                log_audit(st.session_state.user_id, f"LOGGED_JOB: Eq:{e_id} Land:{l_id} Hrs:{hours}")
                st.success("Job hashed and logged successfully.")
            else:
                st.warning("GPS Coordinates are required for Truth Engine verification.")
    
    st.subheader("Job Ledger")
    st.dataframe(pd.read_sql_query("SELECT * FROM works_orders", conn), use_container_width=True)
    conn.close()

# ==========================================
# 7. MODULE: SALES & TWO-TIER PRICING
# ==========================================
elif menu == "Sales & Logistics":
    st.header("Sales & Dispatch")
    with st.container(border=True):
        customer = st.text_input("Customer Name")
        entity_opts = ["Family-Operated Farm", "Corporate / Institutional Entity", "Create New Field..."]
        entity = st.selectbox("Customer Type", entity_opts)
        if entity == "Create New Field...": entity = st.text_input("Enter Custom Entity Type")
        
        turf_type = st.selectbox("Turf Type", ["Sir Walter", "TifTuf", "Eureka", "Create New Field..."])
        if turf_type == "Create New Field...": turf_type = st.text_input("Enter Custom Turf")
        
        qty = st.number_input("Quantity (Sq Mtrs)", min_value=0.0)
        base_price = 10.00 # Example base cost per sqm
        
        final_price = base_price * qty
        if entity == "Corporate / Institutional Entity":
            st.warning("Applying 30% Corporate Surcharge.")
            final_price = final_price * 1.30
            
        st.metric("Total Order Value", f"${final_price:,.2f}")
        
        if st.button("Generate Sales Order"):
            conn = get_db_connection()
            conn.execute("INSERT INTO sales_orders (customer, entity_type, turf_type, qty, final_price, date) VALUES (?, ?, ?, ?, ?, ?)",
                         (customer, entity, turf_type, qty, final_price, str(datetime.now().date())))
            conn.commit()
            log_audit(st.session_state.user_id, f"SALES_ORDER: {customer} - ${final_price}")
            conn.close()
            st.success("Order queued for multi-drop routing.")

# ==========================================
# 8. MODULE: EXECUTIVE DASHBOARD & REPORTS
# ==========================================
elif menu in ["Dashboard", "AI Reports"]:
    st.header(menu)
    if st.session_state.role != 'admin':
        st.error("Executive clearance required.")
    else:
        conn = get_db_connection()
        if menu == "Dashboard":
            st.subheader("Global Audit Ledger (Cryptographic Chain)")
            st.dataframe(pd.read_sql_query("SELECT * FROM audit_log ORDER BY id DESC LIMIT 20", conn), use_container_width=True)
        else:
            st.subheader("Custom AI Report Generator")
            prompt = st.text_area("Define report parameters (e.g., 'Show me Harvest Batch Cost Transparency for all TifTuf paddocks')")
            if st.button("Generate Report"):
                st.info("AI Logic processing... (Placeholder for LLM Query Engine)")
        conn.close()

import streamlit as st
import pandas as pd
import sqlite3
import datetime
import time
from pathlib import Path
import streamlit.components.v1 as components

# --- BRANDING ---
LOGO_URL = "https://images.squarespace-cdn.com/content/v1/5f0d39504a2fa25485e8cdb8/1594704338146-Y44FGCD2TIX74KDGUFST/TurfGalore-LOGO-text_x50%402x.png?format=1500w"

st.set_page_config(page_title="TG Schedule", page_icon=LOGO_URL, layout="wide")

# --- CUSTOM CSS FOR SIDEBAR & LAYOUT ---
st.markdown("""
    <style>
        /* Force the sidebar to be slimmer ONLY on desktop screens. */
        /* On phones (under 768px), let Streamlit auto-collapse it into a slide-out menu! */
        @media (min-width: 768px) {
            [data-testid="stSidebar"] {
                min-width: 220px !important;
                max-width: 220px !important;
            }
        }
    </style>
""", unsafe_allow_html=True)

# --- SCROLL TO TOP HACK (UPGRADED) ---
if "scroll_to_top" not in st.session_state:
    st.session_state.scroll_to_top = False

if st.session_state.scroll_to_top:
    js = f"""
    <script>
        setTimeout(function() {{
            window.parent.scrollTo(0, 0);
            var mainContainer = window.parent.document.querySelector('.main');
            if (mainContainer) {{
                mainContainer.scrollTo(0, 0);
            }}
        }}, 150);
    </script>
    <!-- Cache Buster: {time.time()} -->
    """
    components.html(js, height=0)
    st.session_state.scroll_to_top = False

# --- DATE FORMATTER HELPER ---
def format_aus_date(date_str):
    if not date_str: return ""
    try: return datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")
    except: return date_str

# --- SESSION STATES ---
if "editing_order" not in st.session_state:
    st.session_state.editing_order = None
if "last_menu" not in st.session_state:
    st.session_state.last_menu = None
if "run_date" not in st.session_state:
    st.session_state.run_date = datetime.date.today()
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "current_user" not in st.session_state:
    st.session_state.current_user = None
if "user_role" not in st.session_state:
    st.session_state.user_role = None

# --- DATABASE SETUP ---
DB_PATH = Path("turf_orders_v11.db")

def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Core tables
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
            team_assigned TEXT DEFAULT '',
            parking_pin TEXT DEFAULT '',
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
    
    cursor.execute("PRAGMA table_info(orders)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'team_assigned' not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN team_assigned TEXT DEFAULT ''")
    if 'parking_pin' not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN parking_pin TEXT DEFAULT ''")
    
    # Config tables
    cursor.execute("CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS sites (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL, site_address TEXT NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY AUTOINCREMENT, site_address TEXT NOT NULL, contact_name TEXT NOT NULL, phone TEXT NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS varieties (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS pallet_sizes (id INTEGER PRIMARY KEY AUTOINCREMENT, size INTEGER UNIQUE NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS transport_options (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS teams (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
    
    # User Auth table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            pin TEXT NOT NULL,
            role TEXT NOT NULL
        )
    """)
    
    # Populate defaults if empty
    cursor.execute("SELECT COUNT(*) FROM customers")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO customers (name) VALUES (?)", [("EXCELL GRAY",), ("FLEMINGS",), ("NEDGE",), ("GREEN CONCEPTS",)])
        cursor.execute("INSERT INTO sites (customer_name, site_address) VALUES (?, ?)", ("EXCELL GRAY", "123 Spring St, Melbourne"))
        cursor.execute("INSERT INTO contacts (site_address, contact_name, phone) VALUES (?, ?, ?)", ("123 Spring St, Melbourne", "Dave Foreman", "0412 345 678"))
        cursor.executemany("INSERT INTO varieties (name) VALUES (?)", [("Kikuyu",), ("Santa Anna Couch",), ("Buffalo",)])
        cursor.executemany("INSERT INTO pallet_sizes (size) VALUES (?)", [(60,), (70,), (80,)])
        cursor.executemany("INSERT INTO transport_options (name) VALUES (?)", [("Fleet Truck #1",), ("Fleet Truck #2",), ("Subbie - John Doe Transport",), ("TBA",)])
        cursor.executemany("INSERT INTO teams (name) VALUES (?)", [("Install Team Alpha",), ("Install Team Bravo",), ("TBA",)])
    
    # Default Admin User
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO users (username, pin, role) VALUES (?, ?, ?)", ("admin", "1234", "👑 Ops Manager/Admin"))

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
def get_teams(): return [row[0] for row in run_query("SELECT name FROM teams ORDER BY name ASC")]

def save_new_order(customer, po, site, contact, phone, special, service, transport, team, pin, variety, m2_area, pallet_size, full_pallets, loose_rolls, harvest, install, status):
    existing_sites = get_sites_for_customer(customer)
    if site not in existing_sites and site.strip() != "":
        run_query("INSERT INTO sites (customer_name, site_address) VALUES (?, ?)", (customer, site))
        
    if site.strip() != "" and contact.strip() != "":
        existing_contacts = [c["name"] for c in get_contacts_for_site(site)]
        if contact not in existing_contacts:
            run_query("INSERT INTO contacts (site_address, contact_name, phone) VALUES (?, ?, ?)", (site, contact, phone))
            
    query = """
        INSERT INTO orders (customer, purchase_order, site_address, site_contact, contact_phone, special_instructions, service_type, transport_detail, team_assigned, parking_pin, variety, m2_area, pallet_size, full_pallets, loose_rolls, harvest_date, install_date, status, amount_harvested, amount_installed, remaining_balance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
    """
    run_query(query, (customer, po, site, contact, phone, special, service, transport, team, pin, variety, m2_area, pallet_size, full_pallets, loose_rolls, harvest, install, status, m2_area))

# Initialize database on app start
init_database()

# =====================================================================
# LOGIN SCREEN ENFORCEMENT
# =====================================================================
if not st.session_state.logged_in:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.5, 1])
    
    with col2:
        st.image(LOGO_URL, use_container_width=True)
        st.markdown("<h3 style='text-align: center;'>Schedule & Dispatch Login</h3>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            username = st.text_input("Username").strip().lower()
            pin_input = st.text_input("PIN (Password)", type="password").strip()
            submitted = st.form_submit_button("Log In", use_container_width=True)
            
            if submitted:
                user_record = run_query("SELECT username, role FROM users WHERE LOWER(username)=? AND pin=?", (username, pin_input))
                if user_record:
                    st.session_state.logged_in = True
                    st.session_state.current_user = user_record[0][0].capitalize()
                    st.session_state.user_role = user_record[0][1]
                    st.rerun()
                else:
                    st.error("❌ Invalid Username or PIN")
        
        st.info("💡 **First time?** Try Username: `admin` | PIN: `1234`")
    
    # STOP EXECUTION HERE IF NOT LOGGED IN
    st.stop()


# =====================================================================
# MAIN APP (Only runs if logged in)
# =====================================================================

# --- DYNAMIC LISTS ---
pallet_options = get_pallet_sizes()
varieties = get_varieties()
transport_list = get_transport_options()
teams_list = get_teams()
service_options = ["Supply Only", "Supply & Deliver", "Supply & Install"]
role_options = ["👑 Ops Manager/Admin", "🚜 Farm Staff", "👷 Site Supervisors", "🚚 Linehaul Drivers", "🛠️ Installers"]

# --- SIDEBAR LOGO & USER PROFILE ---
st.sidebar.image(LOGO_URL, use_container_width=True)
st.sidebar.success(f"👤 **{st.session_state.current_user}**\n\n{st.session_state.user_role}")
if st.sidebar.button("🚪 Log Out", use_container_width=True):
    st.session_state.logged_in = False
    st.session_state.current_user = None
    st.session_state.user_role = None
    st.rerun()
st.sidebar.divider()

user_role = st.session_state.user_role

# --- DYNAMIC MAIN MENU ---
st.sidebar.title("Navigation")
if user_role == "👑 Ops Manager/Admin":
    menu_options = ["📊 Pipeline Dashboard", "📋 Daily Run Sheet", "➕ Enter New Order", "👥 Manage Customers", "⚙️ System Settings", "👤 Manage Users"]
else: 
    menu_options = ["📊 Pipeline Dashboard", "📋 Daily Run Sheet"]

menu_selection = st.sidebar.radio("Main Menu:", menu_options)
st.sidebar.divider()

# Reset drill-down & trigger scroll if they click a different menu tab
if st.session_state.last_menu != menu_selection:
    st.session_state.editing_order = None
    st.session_state.last_menu = menu_selection
    st.session_state.scroll_to_top = True
    st.rerun()

# =====================================================================
# GLOBAL DRILL-DOWN OVERLAY
# =====================================================================
if st.session_state.editing_order is not None:
    order_id = st.session_state.editing_order
    
    conn = sqlite3.connect(DB_PATH)
    order_df = pd.read_sql_query(f"SELECT * FROM orders WHERE id = {order_id}", conn)
    conn.close()
    
    if order_df.empty:
        st.error("Order not found.")
        if st.button(f"⬅️ Back to {menu_selection}"):
            st.session_state.editing_order = None
            st.session_state.scroll_to_top = True
            st.rerun()
    else:
        selected_data = order_df.iloc[0]
        total_m2 = int(selected_data['m2_area'])
        harv_val = int(selected_data['amount_harvested'])
        inst_val = int(selected_data['amount_installed'])
        rem_val = int(selected_data['remaining_balance'])
        
        if st.button(f"⬅️ Back to {menu_selection}"):
            st.session_state.editing_order = None
            st.session_state.scroll_to_top = True
            st.rerun()
            
        st.title(f"🔍 Order #{order_id} Drill-Down: {selected_data['customer']}")
        
        with st.container(border=True):
            po_display = selected_data['purchase_order'] if selected_data['purchase_order'] != "" else "N/A"
            
            raw_phone = selected_data['contact_phone']
            if raw_phone and raw_phone.strip() != "":
                clean_phone = raw_phone.replace(" ", "")
                phone_link = f"[{raw_phone} 📞](tel:{clean_phone})"
            else:
                phone_link = "N/A"
                
            raw_pin = selected_data.get('parking_pin', '')
            if raw_pin and raw_pin.strip() != "":
                if raw_pin.startswith("http"):
                    pin_display = f"[📍 Open Map Link]({raw_pin})"
                else:
                    pin_display = f"📍 {raw_pin}"
            else:
                pin_display = "None Provided"
            
            s_col1, s_col2, s_col3 = st.columns(3)
            with s_col1:
                st.markdown(f"**📍 Site Info**\n- **Address:** {selected_data['site_address']}\n- **Contact:** {selected_data['site_contact'] if selected_data['site_contact'] else 'N/A'}\n- **Phone:** {phone_link}")
            with s_col2:
                st.markdown(f"**📋 Logistics**\n- **Cust PO:** {po_display}\n- **Service:** {selected_data['service_type']}\n- **Team:** {selected_data['team_assigned']}\n- **Transport:** {selected_data['transport_detail']}\n- **Harvest:** {format_aus_date(selected_data['harvest_date'])}\n- **Install:** {format_aus_date(selected_data['install_date'])}\n- **Parking:** {pin_display}")
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
                            st.selectbox("Team Assigned", teams_list, index=teams_list.index(selected_data['team_assigned']) if selected_data['team_assigned'] in teams_list else 0, key=f"team_{order_id}")
                        with col2:
                            st.markdown("**2. Progress Update**")
                            st.number_input("Total Harvested (M2)", min_value=0, value=harv_val, step=10, key=f"harv_{order_id}")
                            st.number_input("Total Installed (M2)", min_value=0, value=inst_val, step=10, key=f"inst_{order_id}")
                            st.number_input("Remaining Balance (M2)", value=rem_val, step=1, help="Auto-calculates, but you can override to 0", key=f"rem_{order_id}")
                            st.text_input("📍 B-Double Parking Pin (Link/Note)", value=selected_data.get('parking_pin', ''), key=f"pin_{order_id}")
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
                            st.text_input("📍 Add/Edit B-Double Parking Pin (Link)", value=selected_data.get('parking_pin', ''), key=f"pin_{order_id}")
                        with col2:
                            st.selectbox("Update Pallet Size", pallet_options, index=pallet_options.index(int(selected_data['pallet_size'])) if int(selected_data['pallet_size']) in pallet_options else 0, key=f"pal_{order_id}")
                            status_options = ["Pending", "Locked", "Harvested"]
                            if selected_data['status'] not in status_options: status_options.append(selected_data['status'])
                            st.selectbox("Update Status", status_options, index=status_options.index(selected_data['status']), key=f"stat_{order_id}")
                    
                    elif user_role == "👷 Site Supervisors":
                        st.write("**Site Supervisor Edit Mode** (Installations)")
                        col1, col2 = st.columns(2)
                        with col1:
                            st.number_input("Total Qty Installed (M2)", min_value=0, value=inst_val, step=10, key=f"inst_{order_id}")
                            st.info("Remaining Balance will automatically calculate when you click Save!")
                        with col2:
                            status_options = ["Locked", "Harvested", "Installed"]
                            if selected_data['status'] not in status_options: status_options.append(selected_data['status'])
                            st.selectbox("Update Status", status_options, index=status_options.index(selected_data['status']), key=f"stat_{order_id}")
                            st.text_input("📍 Drop B-Double Parking Pin (Link/Note)", value=selected_data.get('parking_pin', ''), key=f"pin_{order_id}")

                    if st.form_submit_button("💾 Save Order Updates"):
                        
                        final_harv = st.session_state.get(f"harv_{order_id}", harv_val)
                        final_inst = st.session_state.get(f"inst_{order_id}", inst_val)
                        final_rem = st.session_state.get(f"rem_{order_id}", rem_val)
                        
                        final_po = st.session_state.get(f"po_{order_id}", selected_data['purchase_order'])
                        final_srv = st.session_state.get(f"srv_{order_id}", selected_data['service_type'])
                        final_trn = st.session_state.get(f"trn_{order_id}", selected_data['transport_detail'])
                        final_team = st.session_state.get(f"team_{order_id}", selected_data.get('team_assigned', ''))
                        final_pin = st.session_state.get(f"pin_{order_id}", selected_data.get('parking_pin', ''))
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
                            purchase_order=?, service_type=?, transport_detail=?, team_assigned=?, parking_pin=?, special_instructions=?, amount_harvested=?, amount_installed=?, remaining_balance=?, status=?, pallet_size=?, full_pallets=?, loose_rolls=?
                            WHERE id=?
                        """, (final_po, final_srv, final_trn, final_team, final_pin, final_note, final_harv, final_inst, final_rem, final_stat, final_pal, full_pallets, loose_rolls, order_id))
                        
                        st.session_state.editing_order = None
                        st.session_state.scroll_to_top = True
                        st.toast("✅ Order updated successfully!", icon="✅")
                        st.rerun()

# =====================================================================
# ROUTING LOGIC BASED ON MENU (Only runs if NOT drilling down)
# =====================================================================
elif menu_selection == "📊 Pipeline Dashboard":
    st.title("🚜 Ops Dashboard")
    
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
        df['harvest_date'] = df['harvest_date'].apply(format_aus_date)
        df['install_date'] = df['install_date'].apply(format_aus_date)
        
        def row_color(row):
            if row['status'] in ['Installed', 'Cancelled']: return ['background-color: #e2e3e5; color: #6c757d'] * len(row)
            elif row['harvest_date'] != "" and row['install_date'] != "": return ['background-color: #d4edda; color: black'] * len(row)
            return ['background-color: #fff3cd; color: black'] * len(row)
            
        styled_df = df.style.apply(row_color, axis=1)
        
        st.markdown("💡 **Click any row to drill down into the order details.**")
        
        selection_event = st.dataframe(
            styled_df, 
            use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row",
            column_config={
                "id": None, 
                "customer": "Customer", 
                "purchase_order": None, 
                "site_address": "Site", 
                "site_contact": None, 
                "contact_phone": None, 
                "special_instructions": None, 
                "service_type": None, 
                "transport_detail": None, 
                "team_assigned": "Team",
                "parking_pin": None,
                "variety": "Turf", 
                "m2_area": "M2",  
                "pallet_size": None, "full_pallets": None, "loose_rolls": None,
                "harvest_date": "Harvest Date", 
                "install_date": "Install Date", 
                "status": "Status",
                "amount_harvested": "Harv", 
                "amount_installed": "Inst", 
                "remaining_balance": "Bal", 
                "created_at": None
            }
        )
        
        if selection_event.selection.rows:
            selected_row = selection_event.selection.rows[0]
            st.session_state.editing_order = int(df.iloc[selected_row]['id'])
            st.session_state.scroll_to_top = True
            st.rerun()

elif menu_selection == "📋 Daily Run Sheet":
    st.title("📋 Daily Run Sheet")
    
    # --- QUICK JUMP DATE CONTROLS ---
    col1, col2, col3, col4, _ = st.columns([1, 1, 1, 2, 3])
    
    with col1:
        if st.button("⬅️ Prev Day", use_container_width=True):
            st.session_state.run_date -= datetime.timedelta(days=1)
            st.rerun()
    with col2:
        if st.button("Today", use_container_width=True):
            st.session_state.run_date = datetime.date.today()
            st.rerun()
    with col3:
        if st.button("Next Day ➡️", use_container_width=True):
            st.session_state.run_date += datetime.timedelta(days=1)
            st.rerun()
    with col4:
        selected_date = st.date_input("🗓️ Calendar Pop-Up (Click to open)", value=st.session_state.run_date, format="DD/MM/YYYY")
        if selected_date != st.session_state.run_date:
            st.session_state.run_date = selected_date
            st.rerun()

    target_date_str = st.session_state.run_date.strftime("%Y-%m-%d")
    
    conn = sqlite3.connect(DB_PATH)
    harvests = pd.read_sql_query("SELECT id, customer, purchase_order, service_type, team_assigned, transport_detail, site_address, site_contact, contact_phone, variety, m2_area, full_pallets, loose_rolls, special_instructions, status, amount_harvested, amount_installed FROM orders WHERE harvest_date = ? AND status != 'Cancelled'", conn, params=(target_date_str,))
    installs = pd.read_sql_query("SELECT id, customer, purchase_order, service_type, team_assigned, transport_detail, site_address, site_contact, contact_phone, variety, m2_area, full_pallets, loose_rolls, special_instructions, status, amount_harvested, amount_installed FROM orders WHERE install_date = ? AND status != 'Cancelled'", conn, params=(target_date_str,))
    conn.close()
    
    clean_columns = {
        "id": None, 
        "customer": "Customer", "purchase_order": None, "service_type": None, "team_assigned": "Team", "transport_detail": "Transport",
        "site_address": "Site", "site_contact": "Contact", "contact_phone": None, 
        "variety": "Variety", "m2_area": "M2", "full_pallets": "Pallets", 
        "loose_rolls": "Loose", "special_instructions": "Notes", "status": "Status",
        "amount_harvested": "Harv. M2", "amount_installed": "Inst. M2"
    }

    st.subheader(f"🚜 Harvests for {st.session_state.run_date.strftime('%d/%m/%Y')}")
    if harvests.empty: st.info("No harvests scheduled for this date.")
    else: 
        st.markdown("💡 **Click any row to view full order.**")
        sel_harvests = st.dataframe(harvests, use_container_width=True, hide_index=True, column_config=clean_columns, on_select="rerun", selection_mode="single-row")
        if sel_harvests.selection.rows:
            st.session_state.editing_order = int(harvests.iloc[sel_harvests.selection.rows[0]]['id'])
            st.session_state.scroll_to_top = True
            st.rerun()
        
    st.divider()
    
    st.subheader(f"🌱 Installs for {st.session_state.run_date.strftime('%d/%m/%Y')}")
    if installs.empty: st.info("No installs scheduled for this date.")
    else: 
        st.markdown("💡 **Click any row to view full order.**")
        sel_installs = st.dataframe(installs, use_container_width=True, hide_index=True, column_config=clean_columns, on_select="rerun", selection_mode="single-row")
        if sel_installs.selection.rows:
            st.session_state.editing_order = int(installs.iloc[sel_installs.selection.rows[0]]['id'])
            st.session_state.scroll_to_top = True
            st.rerun()

elif menu_selection == "➕ Enter New Order":
    st.title("➕ Queue New Order")
    
    tba_dates = st.checkbox("Send to Pending Pipeline (No Dates)", value=False)
    
    r1_col1, r1_col2 = st.columns(2)
    with r1_col1:
        if not tba_dates:
            install_date = st.date_input("1. Install Date", value=None, format="DD/MM/YYYY")
            default_harvest = (install_date - datetime.timedelta(days=1)) if install_date else None
            harvest_date = st.date_input("2. Harvest Date (Auto)", value=default_harvest, format="DD/MM/YYYY")
        else:
            install_date = None
            harvest_date = None
            st.info("No dates selected (Pending Pipeline)")
    with r1_col2:
        customers = get_customers()
        selected_customer = st.selectbox("3. Select Customer", customers, index=None, placeholder="Choose a Customer...")

    r2_col1, r2_col2 = st.columns(2)
    with r2_col1:
        selected_service = st.selectbox("4. Service Required", service_options, index=None, placeholder="Select Service...")
    with r2_col2:
        variety = st.selectbox("5. Turf Variety", varieties, index=None, placeholder="Select Variety...")

    r3_col1, r3_col2 = st.columns(2)
    with r3_col1:
        m2_area = st.number_input("6. Total Qty Required (M2)", min_value=10, step=10, value=None, placeholder="Enter total area...")
    with r3_col2:
        selected_team = st.selectbox("7. Team Assigned (Optional)", teams_list, index=None, placeholder="Leave blank if unknown...")

    r4_col1, r4_col2 = st.columns(2)
    with r4_col1:
        selected_transport = st.selectbox("8. Transport / Fleet (Optional)", transport_list, index=None, placeholder="Leave blank if unknown...")
    with r4_col2:
        existing_sites = get_sites_for_customer(selected_customer) if selected_customer else []
        site_options = existing_sites + ["➕ Add New Site Address"] if existing_sites else ["➕ Add New Site Address"]
        
        selected_site_option = st.selectbox("9. Job Site Address", site_options, index=None, placeholder="Select or Add New...")
        
        if selected_site_option == "➕ Add New Site Address":
            final_site = st.text_input("Type New Job Site Address:")
        else:
            final_site = selected_site_option if selected_site_option else ""

    r5_col1, r5_col2 = st.columns(2)
    with r5_col1:
        if final_site and final_site != "➕ Add New Site Address":
            existing_contacts = get_contacts_for_site(final_site)
            contact_options = [c["name"] for c in existing_contacts] + ["➕ Add New Contact"] if existing_contacts else ["➕ Add New Contact"]
        else:
            existing_contacts = []
            contact_options = ["➕ Add New Contact"]
            
        selected_contact_option = st.selectbox("10. Site Contact (Optional)", contact_options, index=None, placeholder="Select or Add New...")
        
        if selected_contact_option == "➕ Add New Contact":
            sc_col1, sc_col2 = st.columns(2)
            with sc_col1:
                final_contact = st.text_input("Contact Name (Optional):")
            with sc_col2:
                final_phone = st.text_input("Contact Phone (Optional):")
        else:
            final_contact = selected_contact_option if selected_contact_option else ""
            final_phone = next((c["phone"] for c in existing_contacts if c["name"] == final_contact), "") if final_contact else ""
            if final_contact:
                st.text_input("Phone Number:", value=final_phone, disabled=True)
                
    with r5_col2:
        po_number = st.text_input("11. Customer PO (Optional)", placeholder="e.g. PO-99214")
        parking_pin = st.text_input("📍 B-Double Parking Pin Link (Optional)", placeholder="Paste Google Maps link here...")

    st.divider()
    r6_col1, r6_col2 = st.columns(2)
    with r6_col1:
        selected_pallet = st.selectbox("Pallet Capacity Size (M2)", pallet_options, index=0)
    with r6_col2:
        special_instructions = st.text_area("Special Instructions (Optional)", placeholder="e.g. gate code is 1234...")

    if st.button("💾 Save New Order & Calculate Pallets"):
        if not selected_customer: st.error("Please select a Customer!")
        elif final_site.strip() == "": st.error("Please enter a Job Site address!")
        elif not selected_service: st.error("Please select a Service Required!")
        elif not variety: st.error("Please select a Turf Variety!")
        elif not m2_area: st.error("Please enter a Total M2 Area!")
        elif not selected_pallet: st.error("Please select a Pallet Size!")
        elif not tba_dates and (not harvest_date or not install_date): st.error("Please select both Harvest and Install dates!")
        else:
            full_pallets = int(m2_area // selected_pallet)
            loose_rolls = int(m2_area % selected_pallet)
            
            harvest_str = harvest_date.strftime("%Y-%m-%d") if harvest_date else ""
            install_str = install_date.strftime("%Y-%m-%d") if install_date else ""
            status = "Locked" if harvest_date else "Pending"
            
            clean_contact = final_contact if final_contact else ""
            clean_phone = final_phone if final_phone else ""
            clean_transport = selected_transport if selected_transport else "TBA"
            clean_team = selected_team if selected_team else ""
            clean_pin = parking_pin if parking_pin else ""
            
            save_new_order(selected_customer, po_number, final_site, clean_contact, clean_phone, special_instructions, selected_service, clean_transport, clean_team, clean_pin, variety, m2_area, selected_pallet, full_pallets, loose_rolls, harvest_str, install_str, status)
            st.session_state.scroll_to_top = True
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
                    st.session_state.scroll_to_top = True
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("That customer already exists!")
        
        st.divider()
        with st.expander("🗑️ Delete a Customer"):
            del_cust = st.selectbox("Select Customer to Remove:", customers)
            if st.button("Delete Customer"):
                run_query("DELETE FROM customers WHERE name = ?", (del_cust,))
                st.success(f"Deleted {del_cust}")
                st.session_state.scroll_to_top = True
                st.rerun()

elif menu_selection == "⚙️ System Settings":
    st.title("⚙️ System Settings")
    
    col1, col2, col3, col4 = st.columns(4)
    
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
        st.subheader("🚚 Transport")
        st.dataframe(pd.DataFrame(transport_list, columns=["Fleet / Subbie Name"]), use_container_width=True, hide_index=True)
        
        new_transport = st.text_input("Add Transport:")
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

    with col4:
        st.subheader("👷 Teams")
        st.dataframe(pd.DataFrame(teams_list, columns=["Team Name"]), use_container_width=True, hide_index=True)
        
        new_team = st.text_input("Add Team:")
        if st.button("Save Team"):
            if new_team != "":
                try:
                    run_query("INSERT INTO teams (name) VALUES (?)", (new_team.strip(),))
                    st.success("Team Added!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Team exists!")

        with st.expander("🗑️ Delete Team"):
            del_team = st.selectbox("Select to delete:", teams_list, key="del_team_sel")
            if st.button("Delete", key="del_team_btn"):
                run_query("DELETE FROM teams WHERE name = ?", (del_team,))
                st.rerun()

elif menu_selection == "👤 Manage Users":
    st.title("👤 Manage Users")
    
    conn = sqlite3.connect(DB_PATH)
    users_df = pd.read_sql_query("SELECT id, username, role FROM users", conn)
    conn.close()
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Current Users")
        st.dataframe(users_df, use_container_width=True, hide_index=True, column_config={"id": None, "username": "Username", "role": "Assigned Role"})
        
    with col2:
        st.subheader("➕ Add New User")
        with st.form("new_user_form"):
            new_user = st.text_input("Username (e.g. matt, jason, driver1)").strip().lower()
            new_pin = st.text_input("Assign 4-Digit PIN", type="password").strip()
            new_role = st.selectbox("Assign Role", role_options)
            
            if st.form_submit_button("Save New User"):
                if new_user == "" or new_pin == "":
                    st.error("Please fill out all fields.")
                else:
                    try:
                        run_query("INSERT INTO users (username, pin, role) VALUES (?, ?, ?)", (new_user, new_pin, new_role))
                        st.success(f"User '{new_user}' created successfully!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("That username already exists!")
                        
        st.divider()
        with st.expander("🗑️ Delete User"):
            delete_candidates = users_df[users_df['username'] != st.session_state.current_user.lower()]['username'].tolist()
            if not delete_candidates:
                st.info("No other users to delete.")
            else:
                user_to_delete = st.selectbox("Select user to remove:", delete_candidates)
                if st.button("Delete User", type="primary"):
                    run_query("DELETE FROM users WHERE username = ?", (user_to_delete,))
                    st.success(f"Deleted user '{user_to_delete}'")
                    st.rerun()

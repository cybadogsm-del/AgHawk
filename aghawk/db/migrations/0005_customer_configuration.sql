CREATE TABLE contacts_new (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    site_id TEXT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    UNIQUE (id, organization_id, site_id),
    UNIQUE (id, organization_id, customer_id, site_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (customer_id, organization_id) REFERENCES customers(id, organization_id),
    FOREIGN KEY (site_id, organization_id, customer_id)
        REFERENCES sites(id, organization_id, customer_id)
);

INSERT INTO contacts_new (
    id, organization_id, customer_id, site_id, name, phone, status, created_at
)
SELECT contacts.id, contacts.organization_id, sites.customer_id, contacts.site_id,
       contacts.name, contacts.phone, contacts.status, contacts.created_at
FROM contacts
JOIN sites
  ON sites.id = contacts.site_id
 AND sites.organization_id = contacts.organization_id;

CREATE TABLE orders_new (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    site_id TEXT,
    site_contact_id TEXT,
    purchase_order TEXT NOT NULL DEFAULT '',
    special_instructions TEXT NOT NULL DEFAULT '',
    service_type TEXT NOT NULL DEFAULT '',
    transport_option_id TEXT,
    team_id TEXT,
    parking_pin TEXT NOT NULL DEFAULT '',
    variety_id TEXT NOT NULL,
    m2_area INTEGER NOT NULL CHECK (m2_area > 0),
    pallet_size INTEGER NOT NULL CHECK (pallet_size > 0),
    full_pallets INTEGER NOT NULL DEFAULT 0 CHECK (full_pallets >= 0),
    loose_rolls INTEGER NOT NULL DEFAULT 0 CHECK (loose_rolls >= 0),
    harvest_date TEXT,
    install_date TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    amount_harvested INTEGER NOT NULL DEFAULT 0 CHECK (amount_harvested >= 0),
    amount_installed INTEGER NOT NULL DEFAULT 0 CHECK (amount_installed >= 0),
    remaining_balance INTEGER NOT NULL CHECK (remaining_balance >= 0),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (site_contact_id IS NULL OR site_id IS NOT NULL),
    UNIQUE (id, organization_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (customer_id, organization_id) REFERENCES customers(id, organization_id),
    FOREIGN KEY (site_id, organization_id, customer_id)
        REFERENCES sites(id, organization_id, customer_id),
    FOREIGN KEY (site_contact_id, organization_id, customer_id, site_id)
        REFERENCES contacts_new(id, organization_id, customer_id, site_id),
    FOREIGN KEY (transport_option_id, organization_id)
        REFERENCES transport_options(id, organization_id),
    FOREIGN KEY (team_id, organization_id) REFERENCES teams(id, organization_id),
    FOREIGN KEY (variety_id, organization_id) REFERENCES varieties(id, organization_id)
);

INSERT INTO orders_new (
    id, organization_id, customer_id, site_id, site_contact_id,
    purchase_order, special_instructions, service_type, transport_option_id,
    team_id, parking_pin, variety_id, m2_area, pallet_size, full_pallets,
    loose_rolls, harvest_date, install_date, status, amount_harvested,
    amount_installed, remaining_balance, version, created_at, updated_at
)
SELECT id, organization_id, customer_id, site_id, site_contact_id,
       purchase_order, special_instructions, service_type, transport_option_id,
       team_id, parking_pin, variety_id, m2_area, pallet_size, full_pallets,
       loose_rolls, harvest_date, install_date, status, amount_harvested,
       amount_installed, remaining_balance, version, created_at, updated_at
FROM orders;

CREATE TABLE order_assignments_new (
    organization_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    assignment_role TEXT NOT NULL CHECK (
        assignment_role IN ('site_supervisor', 'driver', 'installer')
    ),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed')),
    assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    removed_at TEXT,
    PRIMARY KEY (organization_id, order_id, user_id, assignment_role),
    FOREIGN KEY (order_id, organization_id)
        REFERENCES orders_new(id, organization_id),
    FOREIGN KEY (organization_id, user_id, assignment_role)
        REFERENCES organization_memberships(organization_id, user_id, role),
    CHECK (
        (status = 'active' AND removed_at IS NULL)
        OR (status = 'removed' AND removed_at IS NOT NULL)
    )
);

INSERT INTO order_assignments_new (
    organization_id, order_id, user_id, assignment_role,
    status, assigned_at, removed_at
)
SELECT organization_id, order_id, user_id, assignment_role,
       status, assigned_at, removed_at
FROM order_assignments;

DROP TABLE order_assignments;
DROP TABLE orders;
DROP TABLE contacts;
ALTER TABLE contacts_new RENAME TO contacts;
ALTER TABLE orders_new RENAME TO orders;
ALTER TABLE order_assignments_new RENAME TO order_assignments;

CREATE INDEX idx_order_assignments_user
    ON order_assignments (organization_id, user_id, assignment_role, status);
CREATE INDEX idx_order_assignments_order
    ON order_assignments (organization_id, order_id, status);
CREATE TRIGGER order_assignments_no_delete
BEFORE DELETE ON order_assignments
BEGIN
    SELECT RAISE(ABORT, 'order assignments must be removed, not deleted');
END;

CREATE INDEX idx_customers_org_name_nocase
    ON customers (organization_id, name COLLATE NOCASE);
CREATE INDEX idx_sites_customer_address_nocase
    ON sites (organization_id, customer_id, address COLLATE NOCASE);
CREATE INDEX idx_contacts_customer_name_nocase_without_site
    ON contacts (organization_id, customer_id, name COLLATE NOCASE)
    WHERE site_id IS NULL;
CREATE INDEX idx_contacts_site_name_nocase
    ON contacts (organization_id, customer_id, site_id, name COLLATE NOCASE)
    WHERE site_id IS NOT NULL;

CREATE INDEX idx_customers_org_status
    ON customers (organization_id, status, name COLLATE NOCASE);
CREATE INDEX idx_sites_customer_status
    ON sites (organization_id, customer_id, status, address COLLATE NOCASE);
CREATE INDEX idx_contacts_customer_status
    ON contacts (organization_id, customer_id, status, name COLLATE NOCASE);
CREATE INDEX idx_contacts_site_status
    ON contacts (organization_id, customer_id, site_id, status, name COLLATE NOCASE);
CREATE INDEX idx_orders_org_status ON orders (organization_id, status);
CREATE INDEX idx_orders_org_harvest_date ON orders (organization_id, harvest_date);
CREATE INDEX idx_orders_org_install_date ON orders (organization_id, install_date);

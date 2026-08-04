CREATE TABLE organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'archived')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    oidc_subject TEXT NOT NULL UNIQUE,
    email TEXT,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE organization_memberships (
    organization_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'farm_staff', 'site_supervisor', 'driver', 'installer')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (organization_id, user_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE customers (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (organization_id, name),
    UNIQUE (id, organization_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
);

CREATE TABLE sites (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    address TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    UNIQUE (id, organization_id, customer_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (customer_id, organization_id) REFERENCES customers(id, organization_id)
);

CREATE TABLE contacts (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    UNIQUE (id, organization_id, site_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (site_id, organization_id) REFERENCES sites(id, organization_id)
);

CREATE TABLE varieties (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (organization_id, name),
    UNIQUE (id, organization_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
);

CREATE TABLE pallet_sizes (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    size INTEGER NOT NULL CHECK (size > 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (organization_id, size),
    UNIQUE (id, organization_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
);

CREATE TABLE transport_options (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    name TEXT NOT NULL,
    pallet_capacity INTEGER NOT NULL DEFAULT 0 CHECK (pallet_capacity >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (organization_id, name),
    UNIQUE (id, organization_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
);

CREATE TABLE teams (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (organization_id, name),
    UNIQUE (id, organization_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
);

CREATE TABLE orders (
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
    FOREIGN KEY (site_contact_id, organization_id, site_id)
        REFERENCES contacts(id, organization_id, site_id),
    FOREIGN KEY (transport_option_id, organization_id) REFERENCES transport_options(id, organization_id),
    FOREIGN KEY (team_id, organization_id) REFERENCES teams(id, organization_id),
    FOREIGN KEY (variety_id, organization_id) REFERENCES varieties(id, organization_id)
);

CREATE TABLE system_config (
    organization_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (organization_id, key),
    UNIQUE (key, organization_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
);

CREATE TABLE audit_events (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    actor_user_id TEXT,
    action TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    before_summary TEXT,
    after_summary TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failure')),
    correlation_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (organization_id, actor_user_id)
        REFERENCES organization_memberships(organization_id, user_id)
);

CREATE TRIGGER audit_events_no_replace
BEFORE INSERT ON audit_events
WHEN EXISTS (SELECT 1 FROM audit_events WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;

CREATE TRIGGER audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;

CREATE TRIGGER audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;

CREATE INDEX idx_memberships_user ON organization_memberships(user_id, status);
CREATE INDEX idx_orders_org_status ON orders(organization_id, status);
CREATE INDEX idx_orders_org_harvest_date ON orders(organization_id, harvest_date);
CREATE INDEX idx_orders_org_install_date ON orders(organization_id, install_date);
CREATE INDEX idx_audit_org_created ON audit_events(organization_id, created_at);

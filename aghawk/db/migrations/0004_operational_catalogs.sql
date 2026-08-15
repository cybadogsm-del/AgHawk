CREATE TABLE service_types (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (organization_id, name),
    UNIQUE (id, organization_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
);

CREATE INDEX idx_varieties_org_name_nocase
    ON varieties (organization_id, name COLLATE NOCASE);
CREATE INDEX idx_transport_options_org_name_nocase
    ON transport_options (organization_id, name COLLATE NOCASE);
CREATE INDEX idx_teams_org_name_nocase
    ON teams (organization_id, name COLLATE NOCASE);
CREATE INDEX idx_service_types_org_name_nocase
    ON service_types (organization_id, name COLLATE NOCASE);

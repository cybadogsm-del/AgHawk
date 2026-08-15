CREATE TABLE brand_assets (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type IN ('image/png', 'image/jpeg')),
    byte_size INTEGER NOT NULL CHECK (byte_size > 0 AND byte_size <= 2097152),
    width INTEGER NOT NULL CHECK (width > 0 AND width <= 4096),
    height INTEGER NOT NULL CHECK (height > 0 AND height <= 4096),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    canonical_bytes BLOB NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    uploaded_by_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TEXT,
    UNIQUE (id, organization_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (organization_id, uploaded_by_user_id)
        REFERENCES organization_memberships(organization_id, user_id),
    CHECK (typeof(canonical_bytes) = 'blob' AND length(canonical_bytes) = byte_size),
    CHECK (width * height <= 16000000),
    CHECK (
        (status = 'active' AND archived_at IS NULL)
        OR (status = 'archived' AND archived_at IS NOT NULL)
    )
);

CREATE TABLE organization_branding (
    organization_id TEXT PRIMARY KEY,
    active_asset_id TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    updated_by_user_id TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (active_asset_id, organization_id)
        REFERENCES brand_assets(id, organization_id),
    FOREIGN KEY (organization_id, updated_by_user_id)
        REFERENCES organization_memberships(organization_id, user_id)
);

INSERT INTO organization_branding (organization_id)
SELECT id FROM organizations;

CREATE TRIGGER organization_branding_after_organization_insert
AFTER INSERT ON organizations
BEGIN
    INSERT INTO organization_branding (organization_id) VALUES (NEW.id);
END;

CREATE TRIGGER brand_assets_no_delete
BEFORE DELETE ON brand_assets
BEGIN
    SELECT RAISE(ABORT, 'brand assets must be archived, not deleted');
END;

CREATE TRIGGER brand_assets_immutable_update
BEFORE UPDATE ON brand_assets
WHEN NOT (
    OLD.status = 'active'
    AND NEW.status = 'archived'
    AND OLD.archived_at IS NULL
    AND NEW.archived_at IS NOT NULL
    AND NEW.id = OLD.id
    AND NEW.organization_id = OLD.organization_id
    AND NEW.content_type = OLD.content_type
    AND NEW.byte_size = OLD.byte_size
    AND NEW.width = OLD.width
    AND NEW.height = OLD.height
    AND NEW.sha256 = OLD.sha256
    AND NEW.canonical_bytes = OLD.canonical_bytes
    AND NEW.uploaded_by_user_id = OLD.uploaded_by_user_id
    AND NEW.created_at = OLD.created_at
)
BEGIN
    SELECT RAISE(ABORT, 'brand asset history is immutable');
END;

CREATE INDEX idx_brand_assets_org_status_created
ON brand_assets(organization_id, status, created_at);

CREATE UNIQUE INDEX idx_memberships_org_user_role
ON organization_memberships(organization_id, user_id, role);

CREATE TABLE order_assignments (
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
        REFERENCES orders(id, organization_id),
    FOREIGN KEY (organization_id, user_id, assignment_role)
        REFERENCES organization_memberships(organization_id, user_id, role),
    CHECK (
        (status = 'active' AND removed_at IS NULL)
        OR (status = 'removed' AND removed_at IS NOT NULL)
    )
);

CREATE INDEX idx_order_assignments_user
ON order_assignments(organization_id, user_id, assignment_role, status);

CREATE INDEX idx_order_assignments_order
ON order_assignments(organization_id, order_id, status);

CREATE TRIGGER order_assignments_no_delete
BEFORE DELETE ON order_assignments
BEGIN
    SELECT RAISE(ABORT, 'order assignments must be removed, not deleted');
END;

CREATE TABLE team_memberships (
    organization_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    membership_role TEXT NOT NULL CHECK (
        membership_role IN ('site_supervisor', 'installer')
    ),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed')),
    joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    removed_at TEXT,
    PRIMARY KEY (organization_id, team_id, user_id, membership_role),
    FOREIGN KEY (team_id, organization_id)
        REFERENCES teams(id, organization_id),
    FOREIGN KEY (organization_id, user_id, membership_role)
        REFERENCES organization_memberships(organization_id, user_id, role),
    CHECK (
        (status = 'active' AND removed_at IS NULL)
        OR (status = 'removed' AND removed_at IS NOT NULL)
    )
);

CREATE INDEX idx_team_memberships_user
ON team_memberships(organization_id, user_id, membership_role, status);

CREATE INDEX idx_team_memberships_team
ON team_memberships(organization_id, team_id, status);

CREATE TRIGGER team_memberships_no_delete
BEFORE DELETE ON team_memberships
BEGIN
    SELECT RAISE(ABORT, 'team memberships must be removed, not deleted');
END;

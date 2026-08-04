# TurfHelm Threat Model

## Purpose

This document explains what TurfHelm must protect, who might try to break it, and what a successful security design must stop.

Think of TurfHelm as a locked office containing several customers' filing cabinets. Logging in opens the building door. Organization separation keeps each customer's cabinet locked. Role permissions decide which drawers a worker may use. Audit history is the security camera recording important changes.

## Protected information

TurfHelm must protect:

- User identities and organization memberships
- Authentication and session information
- Customer and contact details
- Farm, delivery, and installation addresses
- Orders, dates, quantities, turf varieties, and status
- Harvest, transport, and installation progress
- Fleet vehicles, teams, and capacity
- Parking and map locations
- Organization branding and settings
- Audit history
- Database, identity-provider, and deployment secrets
- Backups

## People and failures we defend against

### Anonymous internet visitor

A person with no TurfHelm account may try to read protected pages, guess credentials, upload harmful files, or overload the app.

Required protection: managed login, rate protection, input limits, safe errors, and no anonymous business-data access.

### Ordinary authenticated worker

A legitimate worker may accidentally or deliberately try an action outside their job, such as a driver changing an order.

Required protection: every service operation checks permission; the interface alone is never the lock.

### Worker from another customer

A legitimate user at Farm A may guess or obtain an ID belonging to Farm B.

Required protection: every business query uses the authenticated `organization_id`; IDs supplied by forms or URLs are never trusted as authority.

### Compromised administrator

An attacker may gain control of an administrator account.

Required protection: administrator MFA, least privilege, session controls, high-impact confirmations, audit history, account disabling, and recovery procedures.

### Leaked database or deployment token

A secret may be copied into Git, printed in an error, exposed in a screenshot, or stolen from a device.

Required protection: platform secret storage, least-privilege tokens, rotation, revocation, sanitized errors, and secret scanning.

### Accidental operator mistake

A real user may delete a customer, enter an impossible quantity, overwrite another worker's update, or select the wrong status.

Required protection: validation, safe status transitions, archive instead of deletion, concurrency checks, confirmation, audit history, and recovery.

### Broken dependency or hosting configuration

A package or deployment setting may introduce a vulnerability even when TurfHelm code is correct.

Required protection: pinned dependencies, automated vulnerability scanning, secure deployment configuration, staging tests, and regular updates.

## Trust boundaries

Data crosses a security boundary when it moves between:

1. The user's browser and Streamlit
2. Streamlit and the identity provider
3. Streamlit and Turso
4. One organization and another
5. One role and a more privileged role
6. The live database and backups
7. GitHub and deployment infrastructure

Each boundary must reject missing, invalid, expired, unauthorized, or oversized input.

## Non-negotiable controls

1. Managed OpenID Connect authentication
2. MFA for organization administrators
3. Non-null `organization_id` on every customer-owned record
4. Central service-level authorization
5. Parameterized SQL only
6. Secrets stored outside source control
7. Strict validation and upload limits
8. Append-only audit events for important writes
9. Archive or disable instead of silent destructive deletion
10. Safe error messages that do not expose internals
11. Backups that have been restored in a real test
12. Automated security tests in local verification and CI

## Release blockers

TurfHelm must not contain real customer data or launch commercially while any of these remain:

- Known default administrator credentials
- Plaintext PIN or password storage
- Missing organization isolation
- UI-only authorization
- Unprotected production secrets
- No tested backup recovery
- Unresolved Critical or High security finding

## Security test promise

After each security feature is built, the test suite must try to bypass it. A control is not complete merely because the normal path works. It is complete only when the attack path is tested and denied.

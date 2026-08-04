# TurfHelm

TurfHelm is commercial turf-harvesting logistics and scheduling software.

## Current development status

The working proof-of-concept is preserved at Git commit `d0bc491`.

The `security-foundation` branch rebuilds the application's foundations with security included from the beginning. The existing prototype remains the functional and visual reference; it is not approved for real customer data.

## Safety rules

- Use demonstration data only until the security release gate passes.
- Never commit `.env`, `.streamlit/secrets.toml`, database files, tokens, passwords, PINs, or private keys.
- Do not commit, push, deploy, or treat changes as approved without Stevo's review.
- Every customer organization must be isolated from every other organization.
- Hiding a button is not authorization; service operations must verify permission.
- Every security control requires an automated bypass test.

## Prototype warning

The baseline prototype contains a public demonstration administrator credential, plaintext PIN storage, local SQLite persistence, no organization separation, and no audit trail. It must not be used with real customer or operational data.

## Local verification

Install the pinned runtime and development requirements in a virtual environment, then run:

```bash
scripts/verify.sh
```

The verification gate runs syntax checks, configuration validation, tests, linting, static security analysis, secret scanning, and dependency vulnerability auditing.

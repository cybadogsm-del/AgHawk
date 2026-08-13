# AgHawk

AgHawk is a lightweight Streamlit application for managing small-scale agricultural operations. It provides a secure PIN-based login, land and equipment management, works order logging with cryptographic audit chaining, and a simple sales & logistics module. This repository contains the core app (app.py) and minimal configuration for deployment.

## Features
- PIN-based login with seeded admin account (change before production)
- Land (paddock) and equipment management
- Works orders logging with GPS-based "truth" verification and an audit ledger hashed with SHA-256
- Sales order generation with a simple two-tier pricing model
- Executive dashboard and placeholder AI report generator

## Quick start (local)
1. Clone the repo:

   git clone https://github.com/cybadogsm-del/AgHawk.git
   cd AgHawk

2. Create and activate a virtual environment:

   python -m venv venv
   source venv/bin/activate   # on Windows: venv\Scripts\activate

3. Install dependencies and run:

   pip install -r requirements.txt
   streamlit run app.py

## Deploy (Streamlit Community Cloud)
1. Go to https://share.streamlit.io and sign in with your GitHub account.
2. Click "New app" and select the repository `cybadogsm-del/AgHawk`, branch `main`, and file `app.py`.
3. Click "Deploy" — Streamlit will install dependencies from requirements.txt and launch the app.

## Security & Notes
- The app uses a local SQLite database (aghawk.db). This file is ignored via .gitignore and is created at runtime.
- Change the seeded admin PIN (`0000`) before any public deployment.
- Do not commit production secrets to the repository.

## Next steps (suggested)
- Pin dependency versions in requirements.txt.
- Add tests and a CI pipeline.
- Add a Dockerfile for containerized deployment if desired.

---

Created and committed by GitHub Copilot.

# Publishing The Last Seat to GitHub

This guide is for the complete **v1.3 FastAPI + PostgreSQL + Streamlit** source release. It is **not** a guide for deploying the service to GitHub Pages (a Python API + PostgreSQL server cannot run on GitHub Pages).

## 1. Check your repository contents

The GitHub-ready ZIP contains `README.md`, `requirements.txt`, application and frontend source, SQL setup files, tests, k6 scripts, Compose/Nginx configuration, diagrams and developer documentation. It must not contain real `.env`, `.venv313`, database dumps, student records, session tokens, API keys, or generated bulk k6 outputs. Files matching `.gitignore` are kept off Git when using Git normally.

**Never upload the ZIP as the only file inside your repository.** Extract it, then push the source files. Preserve all folders.

## 2. Create the repository

1. Sign in to [github.com/new](https://github.com/new).
2. Suggested name: `the-last-seat`.
3. Suggested description: `Concurrency-safe concert ticket booking | FastAPI, PostgreSQL, Streamlit, FIFO waitlist and k6 load testing`.
4. Select Public or Private depending on your submission instructions. If Public, double-check that no real passwords or students' personal information are present.
5. **Do not initialize** the empty repository with a README or license: this ZIP already includes a README.
6. Click **Create repository** and copy your own GitHub repository URL.

## 3. Push from Windows PowerShell (recommended)

From inside the **extracted source folder** (the folder that contains `app`, `frontend`, `README.md`, `requirements.txt`):

```powershell
git --version
git init
git branch -M main
git add .
git status
git commit -m "Initial release: The Last Seat FastAPI and Streamlit"
git remote add origin https://github.com/YOUR_USERNAME/the-last-seat.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your own username (and use the exact URL GitHub shows). If Git says you need an identity, run:

```powershell
git config --global user.name "YOUR DISPLAY NAME"
git config --global user.email "YOUR_GITHUB_EMAIL"
```

GitHub may ask you to sign in with Git Credential Manager or authenticate with a personal access token. **Do not paste passwords or tokens into the repository or this chat.** If you have already added an `origin`, check `git remote -v` rather than running `git remote add origin` again.

Before pushing, inspect `git status` to confirm `.env`, `.venv313`, caches, log files, and generated test result JSON are absent. Run `git status --short` afterward to see any local changes.

## 4. Alternative GitHub web upload

On your **empty** GitHub repository, choose **Add file → Upload files**, drag the extracted project files and folders (not the single ZIP), then commit. The command-line path is easier for preserving nested directories and updating the project later.

## 5. What to show reviewers

- README quick start and features
- `docs/DIAGRAMS.md`: database ERD and booking workflow
- `docs/ARCHITECTURE.md`: PostgreSQL row locks, unique indexes, idempotency and FIFO waitlist
- `docs/TEST_REPORT.md`: the **operator-provided** 10,000-iteration result and evidence limitations
- `docs/DECISIONS.md`: tradeoffs and constraints
- `frontend/streamlit_app.py`: clickable seats, login, reservation and sign-out
- `loadtests/race.js`: `shared-iterations` setup and valid-outcome checks

For screenshots, launch the project locally and take your own images from `/docs` and Streamlit. No screenshots of the private database or token strings are included in this release.

## 6. Important limitations

- Tested concurrency used 200 k6 VUs for 10,000 total attempts, **not 10,000 simultaneous connections**.
- User-provided results came from a Windows-native run with PostgreSQL and Redis intentionally disabled. Docker, Redis, RabbitMQ, Nginx and public cloud runtime operation are not proven by that run.
- Simulated payments are not real payment processing.
- No cloud deployment, GitHub Actions run or public production hardening has been verified here.
- Automated unit tests do not replace a manual Streamlit browser demonstration.
- Repository publication **does not delete** temporary data from your local PostgreSQL installation. Use the guarded cleanup utility only after previewing its target and stopping the API/worker.

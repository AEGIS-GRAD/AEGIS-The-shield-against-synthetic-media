# 🛡️ AEGIS — Weights & Biases Setup Guide

This guide walks every team member through connecting the AEGIS experiment
tracker to the shared **AEGIS-GRAD** W&B workspace in under 5 minutes.

---

## 1. Create a W&B Account

1. Go to **[https://wandb.ai/signup](https://wandb.ai/signup)**
2. Sign up with your university email (or GitHub/Google)
3. Ask the project lead to **invite you** to the `AEGIS-GRAD` team at:
   ```
   https://wandb.ai/AEGIS-GRAD/members
   ```

---

## 2. Install the W&B Library

```bash
python -m pip install wandb
```

Or install all project dependencies at once:

```bash
python -m pip install -r requirements.txt
```

---

## 3. Get Your API Key

1. Log in to [https://wandb.ai](https://wandb.ai)
2. Click your avatar → **User Settings** → **API Keys**
   - Direct link: **[https://wandb.ai/authorize](https://wandb.ai/authorize)**
3. Copy the key — it looks like:  
   `a1b2c3d4e5f6g7h8i9j0...` (40 characters)

> ⚠️ **Never commit your API key to git.** Treat it like a password.

---

## 4. Link Your Machine to W&B

Run this **once** — the key is saved permanently to your machine:

```bash
python -m wandb login YOUR_API_KEY_HERE
```

**Example:**
```bash
python -m wandb login a1b2c3d4e5f6g7h8i9j0abcdef123456789012
```

You should see:
```
wandb: Appending key for api.wandb.ai to your netrc file: C:\Users\you\.netrc
wandb: Currently logged in as: your-username (AEGIS-GRAD). Use `wandb logout` to log out.
```

---

## 5. Verify the Connection

```bash
python -m wandb verify
```

A successful output looks like:
```
wandb: Verifying connection to https://api.wandb.ai ...
wandb: Connection verified successfully.
```

---

## 6. Run the Smoke Test

```bash
python test_run.py
```

If everything is configured correctly you will see:

```
wandb: Currently logged in as: your-username (AEGIS-GRAD)
wandb: Tracking run with wandb version x.x.x
wandb: Run data is saved locally in ./wandb/run-...
wandb: Syncing run <run-name> to: https://wandb.ai/AEGIS-GRAD/AEGIS-The-shield-against-synthetic-media
Smoke test run logged successfully.
```

Then open the link printed in the terminal to see your run in the dashboard.

---

## 7. View the Team Dashboard

All runs from every team member land in one shared project:

```
https://wandb.ai/AEGIS-GRAD/AEGIS-The-shield-against-synthetic-media
```

---

## Alternative: Offline Mode (No Internet)

If you're working without internet access (e.g., in the lab), set this
environment variable **before** running any script:

```powershell
# Windows PowerShell
$env:WANDB_MODE = "offline"
python test_run.py
```

```bash
# Linux / macOS
WANDB_MODE=offline python test_run.py
```

Sync your offline runs when you're back online:

```bash
wandb sync wandb/offline-run-*
```

---

## Common Issues

| Error | Fix |
|-------|-----|
| `No API key configured` | Run `python -m wandb login YOUR_KEY` |
| `Entity 'AEGIS-GRAD' not found` | Ask the project lead to invite you to the team |
| `wandb: not recognized` | Run with `python -m wandb` instead of `wandb` |
| `CommError: Network timeout` | Check internet or use `WANDB_MODE=offline` |

---

## Quick Reference

```bash
python -m wandb login          # Log in interactively
python -m wandb login <key>    # Log in with key directly
python -m wandb logout         # Log out
python -m wandb verify         # Test connection
python -m wandb status         # Show current login status
wandb sync wandb/offline-run-* # Sync offline runs
```

---

*For questions, contact the project lead or open an issue in the AEGIS repo.*

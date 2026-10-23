# 3G OILS Dashboard - New Computer Setup Guide

Follow these steps in order on a brand new computer with nothing installed.

---

## PART 1 - Install Required Software

### Step 1: Install Python

1. Go to https://www.python.org/downloads/
2. Click **"Download Python 3.11"** (or latest 3.11.x)
3. Run the installer
4. **IMPORTANT:** Check the box **"Add Python to PATH"** before clicking Install
5. Click **"Install Now"**
6. Verify: open Command Prompt and run:
   ```
   python --version
   ```
   Should show: `Python 3.11.x`

---

### Step 2: Install Git

1. Go to https://git-scm.com/download/win
2. Download and run the installer
3. Click **Next** through all steps (default settings are fine)
4. Verify: open Command Prompt and run:
   ```
   git --version
   ```
   Should show: `git version 2.x.x`

---

### Step 3: Install Microsoft Access ODBC Driver

> Required only if you want to export data from the `.mdb` file.
> Skip this step if you only want to **view** the dashboard (read CSVs only).

1. Go to https://www.microsoft.com/en-us/download/details.aspx?id=54920
2. Download **AccessDatabaseEngine_X64.exe** (64-bit)
3. Run the installer, click through defaults
4. Verify: open Command Prompt and run:
   ```
   python -c "import pyodbc; print([d for d in pyodbc.drivers() if 'Access' in d])"
   ```
   Should show: `['Microsoft Access Driver (*.mdb, *.accdb)']`

---

## PART 2 - Get the Code

### Step 4: Clone the GitHub Repository

1. Open **Command Prompt**
2. Navigate to where you want the project (e.g., Desktop):
   ```
   cd C:\Users\YourName\Desktop
   ```
3. Clone the repo:
   ```
   git clone https://github.com/krishnasai-narayana/3goils.git
   ```
4. Go into the project folder:
   ```
   cd 3goils
   ```

---

### Step 5: Copy the Database File

> The `.mdb` file is NOT on GitHub (too large, Windows-only).
> Copy it from the original computer or a USB drive.

1. Get the file `3G2026.mdb` from:
   - USB drive, or
   - Original computer at: `...\3goils-streamlit\database\3G2026.mdb`
2. Paste it into the `database\` folder inside the cloned project:
   ```
   C:\Users\YourName\Desktop\3goils\database\3G2026.mdb
   ```

---

## PART 3 - Install Python Packages

### Step 6: Install Dependencies

Open Command Prompt **inside the project folder** and run:

```
pip install -r requirements.txt
```

If you also want to export from the `.mdb` file (Step 3 done), also install:

```
pip install pyodbc
```

---

## PART 4 - Run the Dashboard

### Step 7: Start the App

In Command Prompt inside the project folder, run:

```
python -m streamlit run app.py
```

The browser will open automatically at **http://localhost:8501**

> Or access the live cloud version anytime at: **https://3goils.streamlit.app**

---

## PART 5 - Update Data (When MDB File Changes)

### Step 8: Configure Git Identity (One Time)

Run these once in Command Prompt:

```
git config --global user.email "your@email.com"
git config --global user.name "Your Name"
```

### Step 9: Set Up GitHub Authentication (One Time)

Git needs a Personal Access Token to push to GitHub:

1. Go to https://github.com → Sign in as `krishnasai-narayana`
2. Click your profile photo → **Settings**
3. Left sidebar → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
4. Click **"Generate new token (classic)"**
5. Give it a name (e.g., `3goils-laptop`)
6. Check scope: **repo** (full control)
7. Click **Generate token**
8. **Copy the token** - you will not see it again

When Git asks for a password the first time you push, paste this token.

---

### Step 10: Update Data Workflow

Whenever the `3G2026.mdb` file is updated with new billing data:

1. Copy the new `3G2026.mdb` into the `database\` folder
2. Double-click **`update_data.bat`** in the project folder
3. It will:
   - Export all CSVs from the `.mdb` file automatically
   - Commit changes with today's date
   - Push to GitHub
4. The live app at **https://3goils.streamlit.app** auto-updates within **2 minutes**
5. Hard refresh the browser: **Ctrl + Shift + R**

---

## Quick Reference

| Task | Command |
|------|---------|
| Start the app locally | `python -m streamlit run app.py` |
| Update data and push | Double-click `update_data.bat` |
| Pull latest code changes | `git pull origin main` |
| Install/update packages | `pip install -r requirements.txt` |

| Location | Path |
|----------|------|
| Project folder | `...\3goils\` |
| Database file | `...\3goils\database\3G2026.mdb` |
| CSV data files | `...\3goils\data\*.csv` |
| Update script | `...\3goils\update_data.bat` |
| Live app URL | https://3goils.streamlit.app |
| GitHub repo | https://github.com/krishnasai-narayana/3goils |

---

## Troubleshooting

**`python` not recognized**
→ Re-run Python installer and check "Add Python to PATH"

**`git` not recognized**
→ Restart Command Prompt after Git installation

**`push` rejected / authentication failed**
→ Use your GitHub Personal Access Token as the password (not your GitHub login password)

**App shows old data after pushing**
→ Wait 2 minutes, then press Ctrl+Shift+R on the browser
→ If still old, go to https://share.streamlit.io → find app → ⋮ → Reboot app

**Access ODBC driver not found**
→ Install the 64-bit driver from Microsoft (Step 3)
→ Must match your Python bitness (64-bit Python needs 64-bit driver)

**`update_data.bat` fails at export step**
→ Check that `3G2026.mdb` is in the `database\` folder
→ Check that the Access ODBC driver is installed (Step 3)
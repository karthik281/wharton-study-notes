# CLAUDE.md — Wharton Study Notes Agent

## PowerShell Command Rules

Do not use compound PowerShell commands with `cd` followed by another command.

When running scripts in this project, use absolute paths instead.

**Wrong:**
```powershell
cd "C:\Users\raoka\Documents\Ideas\Agents\Wharton Study Notes"; venv\Scripts\python script.py
```

**Correct:**
```powershell
& "C:\Users\raoka\Documents\Ideas\Agents\Wharton Study Notes\venv\Scripts\python.exe" "C:\Users\raoka\Documents\Ideas\Agents\Wharton Study Notes\script.py"
```

Use this absolute-path pattern for all script execution in this project.

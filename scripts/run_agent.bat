@echo off
cd /d "C:\Users\raoka\Documents\Ideas\Agents\Wharton Study Notes"
if not exist logs mkdir logs
venv\Scripts\python agent.py >> logs\agent.log 2>&1
venv\Scripts\python scripts\download_videos.py >> logs\download.log 2>&1

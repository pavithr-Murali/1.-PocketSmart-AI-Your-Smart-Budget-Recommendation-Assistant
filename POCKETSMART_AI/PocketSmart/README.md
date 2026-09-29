# PocketSmart AI: Smart Budget and Recommendation Assistant

FastAPI + Gemini + Jinja2. Three planners (Home, Party, Jewelry) with login, history and shopping links.

## Setup in VS Code
1. Install Python 3.10+ and VS Code with the "Python" extension.
2. VS Code: File > Open Folder > select the `PocketSmart` folder.
3. Terminal > New Terminal, then:
   - `python -m venv venv`
   - Windows: `venv\Scripts\activate` (PowerShell: if blocked, run `Set-ExecutionPolicy -Scope Process Bypass` first)
   - macOS/Linux: `source venv/bin/activate`
   - `pip install -r requirements.txt`
4. Press Ctrl+Shift+P, choose "Python: Select Interpreter", pick the one inside `venv`.
5. Get a free key at https://aistudio.google.com (Get API key > Create API key).
6. Copy `.env.example` to `.env` (Windows: `copy .env.example .env`) and paste your key into `GEMINI_API_KEY`.
   Optionally set `GEMINI_MODEL` (default `gemini-2.5-flash`) and a random `SECRET_KEY`.

## Run
`python main.py`  (or `uvicorn main:app --reload`)  then open http://127.0.0.1:8000
Interactive API docs: http://127.0.0.1:8000/docs

## Test
1. Register at /register, then sign in.
2. Home planner: submit the default form; check the summary, category tables and shopping chips.
3. Party planner: try another party type and untick some needs.
4. Jewelry planner: submit once without and once with an outfit photo (PNG/JPG/WEBP, under 5 MB); the photo run adds an outfit analysis.
5. History (/history): open "View details" on each entry.
6. Fallback test: blank out `GEMINI_API_KEY`, restart, run a planner. A yellow notice appears with default suggestions.
7. Also open /session-info while logged in.

## Troubleshooting
- "AI unavailable" notice: check the key, your internet connection and that `GEMINI_MODEL` is a current model name.
- `ModuleNotFoundError`: the venv is not active or step 3 was skipped.
- Redirected to /login: your session lasts 30 minutes; sign in again.
- Data is stored in `pocketsmart.db` (delete it to reset all users and history).

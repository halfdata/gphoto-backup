# Google Photos Backup
This tool allows you to download media items from Google Photos and keep them locally.

### How to install the tool?
It's a pretty standard way:
1. Download the tool or clone git repository.
2. Make sure that you have Python 3.6 or higher.
3. Create venv and switch to it (optional):
   ```
   python -m venv .venv
   .venv/Scripts/Activate
   ```
4. Install dependencies from `requirements.txt`:
   ```
   pip install -r requirements.txt
   ```


### How to use the tool?
Unfortunately, the only way to access Google Photos Library API is an access using OAuth 2.0 tokens (no API keys, no service accounts). So the first step is authenticate the tool to access your Google Account.
1. Run auth.py in terminal:
   ```
   python auth.py
   ```
2. Open `http://localhost:8080` in your browser and follow the instructions to get access token. When you finish, the token is saved in local SQLite database.
3. Go back to terminal and stop `auth.py` by pressing Ctrl+C (or Command+C). Never leave it running.
4. Start downloading your library:
   ```
   python main.py
   ```

More detailed documentation is coming soon...
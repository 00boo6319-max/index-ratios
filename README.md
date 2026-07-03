# TIPS ladder calculator — auto-refresh setup

This folder contains everything needed to have your TIPS index ratios update
automatically once a day, with no manual copy-paste, and the calculator
picking up fresh values every time you open it.

## What's in here

- `tips_ladder_calculator.html` — the calculator itself. Open this in a browser.
- `fetch_index_ratios.py` — fetches current Index Ratios from TreasuryDirect
  for your 13 CUSIPs, writes `index_ratios.json`.
- `index_ratios.json` — seed data (values as of 2026-07-03) so the calculator
  works immediately, before your first scheduled run.
- `.github/workflows/update-ratios.yml` — a GitHub Action that runs the
  script daily and commits the updated JSON automatically.

## One-time setup (about 5 minutes)

1. **Create a new GitHub repository.**
   Go to github.com, click "New repository." Make it **public** (a private
   repo works too, but then `raw.githubusercontent.com` requires
   authentication, which defeats the point of a simple browser fetch — public
   is simplest unless you're comfortable adding a token). Name it whatever
   you like, e.g. `tips-ladder`.

2. **Upload all the files in this folder**, preserving the folder structure —
   `.github/workflows/update-ratios.yml` needs to stay at that exact path.
   Easiest way: on the repo's GitHub page, use "Add file" → "Upload files"
   and drag the whole folder in, or use `git` from the command line:

   ```
   cd tips-ladder-repo
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git push -u origin main
   ```

3. **Enable Actions** if prompted (usually on by default for new repos).
   Go to the "Actions" tab of your repo and confirm the "Update TIPS index
   ratios" workflow appears. You can click "Run workflow" to trigger it
   immediately instead of waiting for the daily schedule.

4. **Edit `tips_ladder_calculator.html`.**
   Find this line near the top of the `<script>` section:

   ```js
   const GITHUB_RAW_URL = 'https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/index_ratios.json';
   ```

   Replace `YOUR_USERNAME/YOUR_REPO` with your actual GitHub username and
   repo name. Save the file.

5. **Open the calculator.** It will try to fetch the JSON from your repo
   automatically on load, and you can also click "Refresh from GitHub" any
   time. If the fetch fails, it just keeps the last known values and shows
   you why in the status line — nothing breaks silently.

## Ongoing maintenance

- Nothing. The Action runs daily on its own and commits `index_ratios.json`
  whenever the ratios change.
- If your holdings change (new CUSIP bought, one matures and is removed),
  edit the `CUSIPS` list in `fetch_index_ratios.py` and the `holdings` array
  in `tips_ladder_calculator.html` to match.
- If you ever want to check that it's still running, look at the "Actions"
  tab of your repo — each day's run is logged there.

## If you'd rather not use GitHub

The manual "paste updater output" box in the calculator still works exactly
as before — run `fetch_index_ratios.py` locally whenever you like and paste
its console output into that box instead.

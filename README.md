# Remittance Survey dashboard

One dashboard for both questionnaires (Bangla and English). GitHub fetches the
data from Dropbox on a schedule, merges the two, and publishes a page that
shows totals and statistics, never names or full interviews.

```
Dropbox (CSPro sync) --> GitHub Action --> site/data.json --> GitHub Pages
                         fetch, merge,     totals only        the dashboard
                         convert, count
```

## What is in here

| Path | What it does |
|---|---|
| `site/index.html` | The dashboard page. Reads `data.json` from the same folder. |
| `pipeline/make_login.py` | Makes the sign-in code when you change the username or password. |
| `pipeline/fetch_dropbox.py` | Downloads the latest data from Dropbox. |
| `pipeline/build.py` | Merges both questionnaires, converts currencies, writes `site/data.json`. |
| `pipeline/spec.py` | The list of charts, module by module. Edit to add, remove or rename a chart. |
| `pipeline/cspro_read.py` | Reads CSPro data (`.csdb` files and CSPro's Dropbox sync files). |
| `config/settings.json` | Exchange rates, targets, privacy switches, answer-code fixes. |
| `dict/` | The two dictionaries. Replace them whenever the forms change. |
| `.github/workflows/update.yml` | The schedule: runs every 15 minutes and on demand, the same as the SERWE dashboard. |

## Setup (about 20 minutes, once)

### 1. Put this folder on GitHub

Create a new repository, upload everything in this folder, and keep the default
branch name `main`. A public repository is fine: the raw data is never stored
in it. (GitHub Pages from a private repository needs a paid or student plan.)

### 2. Let GitHub read the Dropbox folder

This project uses the same three secrets as the SERWE dashboard (`DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`). If this survey syncs to the same Dropbox account and you still have those three values, skip to point 6 and add them to this repository.

Sign in to **the Dropbox account the tablets sync to**, then:

1. Open <https://www.dropbox.com/developers/apps> → **Create app** → *Scoped access* → *Full Dropbox* → give it any name.
2. On the **Permissions** tab tick `files.metadata.read` and `files.content.read`, then **Submit**.
3. On the **Settings** tab copy the **App key** and **App secret**.
4. Open this address in the browser (put your App key in it), press **Allow**, and copy the code it shows:

   `https://www.dropbox.com/oauth2/authorize?client_id=APP_KEY&response_type=code&token_access_type=offline`

5. In Command Prompt run this (one line), replacing the three values:

   `curl https://api.dropboxapi.com/oauth2/token -d code=THE_CODE -d grant_type=authorization_code -u APP_KEY:APP_SECRET`

   The answer contains `"refresh_token": "..."`. Copy that value. It does not expire.

6. In the GitHub repository go to **Settings → Secrets and variables → Actions → New repository secret** and add three secrets:
   `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`.

### 3. Turn on GitHub Pages

**Settings → Pages → Build and deployment → Source: GitHub Actions.**

### 4. First run

**Actions → Update dashboard → Run workflow.** When it turns green the page is
live at `https://YOUR-NAME.github.io/REPO-NAME/`. The run log prints how many
interviews it read from each questionnaire.

### 5. Your DuckDNS address (optional)

1. In DuckDNS set the *current ip* of your subdomain to `185.199.108.153`.
2. In GitHub: **Settings → Pages → Custom domain** → `yourname.duckdns.org` → Save.
3. When the DNS check passes, tick **Enforce HTTPS**. This can take up to a day.
   If it stays stuck, the `github.io` address keeps working.

## Signing in

The page opens with a sign-in screen. It ships with username `pri` and password
`remit2026`. To change them run `python pipeline/make_login.py NEWUSER NEWPASSWORD`
and paste the line it prints over the `var HASH='...'` line in `site/index.html`.

The sign-in keeps casual visitors out. It is not strong protection: the totals
file `data.json` can still be opened by anyone who knows its address.

## Where the data comes from

`config/settings.json → fetch.mode` has two options.

- **`"sync"` (default).** Reads the files CSPro itself keeps in Dropbox under
  `/CSPro/DataSync/<DICTIONARY NAME>/data/`. No PC needs to be switched on.
- **`"csdb"`.** Downloads the two `.csdb` files from the Dropbox folder named in
  `fetch.dropbox_csdb_folder`. Use this if a PC already runs the two
  `DownloadData-*.pff` files into a Dropbox folder every day.

To build on your own PC instead (no Dropbox, no GitHub):

```
python pipeline/build.py --csdb bn=remittance_survey_2026_dict.csdb en=remittance_survey_english_dict.csdb
cd site
python -m http.server 8000        (then open http://localhost:8000)
```

## Settings you will want to change

| Setting | Meaning |
|---|---|
| `rates_per_usd` | Starting exchange rates: units of each currency per 1 USD. **The values supplied are placeholders.** Anyone can try other rates in the page's currency section, but those stay on their own device; change them here to change them for everyone. |
| `targets` | Target number of completed interviews per country code (101 Malaysia, 102 Saudi Arabia, 103 UAE, 104 UK, 105 USA). Leave `null` for none. |
| `privacy.show_staff_names` | `true` shows names from the dictionary; `false` shows "Interviewer 07". Codes missing from the dictionary always show as numbers. |
| `privacy.min_n_for_statistics` | Medians, averages and ranges are hidden below this many answers. |
| `privacy.list_flagged_case_ids` | Show the ID codes of interviews that need checking. |
| `privacy.publish_open_text` | Open-text questions whose most common answers are shown. Remove a name to hide it. |
| `aliases` | English spelling for typed answers (city, provider), e.g. `"রিয়াদ": "Riyadh"`. Typed answers still in Bangla show as "Not yet translated" and are listed in the update log so you can add them. |
| `recodes` | Answer codes that changed between versions of the forms (old code → new code). |
| `results_include_reopened` | Count interviews that were completed, then reopened and not closed again, in the results. |
| `channel_amount_currency` | The D1 channel amounts have no currency question; they are converted with this field's currency. |

## How the two questionnaires are combined

- Interviews are matched by variable name; both forms use the same names.
- Both questionnaires are drawn together in every chart, in two colours, with a country filter on top.
- Labels shown are the English ones from `dict/REMITTANCE_SURVEY_ENGLISH_DICT.dcf`.
- Deleted interviews are ignored. Partly filled and refused interviews appear
  only on the Fieldwork page.
- Every build logs any answer code that is in the data but not in the
  dictionary, and the Fieldwork page lists them.

## What the data file contains

`site/data.json` holds counts per day, country and questionnaire for every choice
question, and for each number question the list of answers with their day,
country and questionnaire. That is what lets the page filter by date and
re-convert currencies. It does not hold names, and answers to different
questions cannot be joined back into one person's interview. ID codes are
included only for interviews flagged in the data checks and for outliers.

## Good to know

- GitHub pauses scheduled runs in a repository with no activity for 60 days.
  Any commit, or pressing **Run workflow**, starts them again.
- Scheduled runs can start several minutes late when GitHub is busy.
- `python tests/test_sync_reader.py file.csdb dict/NAME.dcf` checks the two
  readers against each other.

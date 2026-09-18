# a-jobseeker

A command line tool that:

1. Scrapes job offers from various websites.
2. Selects the ones that match your profile, using an AI.
3. Generates a tailored PDF CV and cover letter for each selected offer.
4. Outputs the list (application link + CV + cover letter).

## Installation

- From PyPI:

```bash
pip install a-jobseeker
```

On systems protecting their Python installation (Debian, Ubuntu...),
install it with [uv](https://docs.astral.sh/uv/) (`uv tool install a-jobseeker`)
or [pipx](https://pipx.pypa.io) (`pipx install a-jobseeker`) instead.

- Or from the GitHub repository:

```bash
mkdir -p ~/.local/src
cd ~/.local/src

REPO_NAME=a-jobseeker

git clone https://github.com/Skalyaev/$REPO_NAME.git
cd $REPO_NAME && pip install .
```

An AI command line program is required.
[Claude Code](https://claude.com/claude-code) (`claude`) is used by default,
but any other AI CLI can be plugged in (see [AI providers](#ai-providers)).

## Quick start

```bash
a-jobseeker init # creates example config.json and profile.json files in ~/.config/a-jobseeker

# ... edit profile.json (your profile) and config.json (your searches)

a-jobseeker run # scrapes, selects and generates the applications
```

Example output:

```
1 offer(s) matching your profile:

[1] Software Engineer (H/F) - CDI - Paris - Wiremind (Paris)
    Score        : 85/100
    Why          : Junior fullstack role in Paris matching the candidate's Python and FastAPI experience.
    Apply        : https://www.linkedin.com/jobs/view/4446409330/
    CV           : ~/.local/share/a-jobseeker/applications/2026-09-18/linkedin-Wiremind-Software-Engineer-4446409330/cv.pdf
    Cover letter : ~/.local/share/a-jobseeker/applications/2026-09-18/linkedin-Wiremind-Software-Engineer-4446409330/cover-letter.pdf
```

## Commands

| Command                                   | Description                                                                                                                   |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `a-jobseeker init [--force]`              | Creates example `config.json` and `profile.json` files in the configuration directory                                         |
| `a-jobseeker run`                         | Runs the whole pipeline (options below)                                                                                       |
| `a-jobseeker scrape -o jobs.json`         | Scrapes the offers without calling the AI (useful to test your searches)                                                      |
| `a-jobseeker render .../application.json` | Renders the PDFs again after manually editing the generated content in `application.json` (see [How it works](#how-it-works)) |
| `a-jobseeker dirs`                        | Prints the configuration, data and cache directories                                                                          |
| `a-jobseeker list`                        | Lists the available sources, AI providers, outputs and templates                                                              |

Options available on every command:

| Option             | Description                                                                                     |
| ------------------ | ----------------------------------------------------------------------------------------------- |
| `--config-dir DIR` | Directory of `config.json` and `profile.json` (default: `~/.config/a-jobseeker`)                |
| `--data-dir DIR`   | Directory of the generated applications and run history (default: `~/.local/share/a-jobseeker`) |
| `--cache-dir DIR`  | Directory of the cached offers (default: `~/.cache/a-jobseeker`)                                |
| `-v`, `-vv`        | Shows the progress, or the details (including the score and reason of every evaluated offer)    |

`run` options:

| Option                | Description                                                   |
| --------------------- | ------------------------------------------------------------- |
| `-o`, `--output TYPE` | How the results are published (see [Outputs](#outputs))       |
| `--ai PROVIDER`       | AI provider to use (see [AI providers](#ai-providers))        |
| `--ai-path PATH`      | Path of the AI command line program                           |
| `--limit N`           | Maximum number of offers sent to the AI                       |
| `--jobs-file FILE`    | Uses offers saved by `scrape` instead of scraping             |
| `--ignore-seen`       | Evaluates again the offers already processed by previous runs |

## Files and directories

| Directory                    | Content                                                                             |
| ---------------------------- | ----------------------------------------------------------------------------------- |
| `~/.config/a-jobseeker`      | `config.json` and `profile.json`                                                    |
| `~/.local/share/a-jobseeker` | `applications/`: the generated documents; `seen.json`: the offers already evaluated |
| `~/.cache/a-jobseeker`       | `offers/`: the scraped offer details, kept `scraping.cache_max_age_days` days       |

When set, `$XDG_CONFIG_HOME`, `$XDG_DATA_HOME` and `$XDG_CACHE_HOME` replace `~/.config`,
`~/.local/share` and `~/.cache`. The command line options take precedence over both.

Thanks to `seen.json`, a periodic run (cron) only evaluates new offers. Thanks to the cache, offers
that could not be evaluated yet are not downloaded again. The cache can be deleted at any time.

## The profile (`profile.json`)

The profile is sent as-is to the AI: its structure is free, add anything that may help.

Only these fields are read by the program itself:

- `identity`: copied verbatim into the documents, never generated by the AI.
  `first_name` is required, every other field is optional.

- `preferences.banned_companies` and `preferences.banned_title_keywords`: filters applied **before**
  calling the AI (whole word, case insensitive, on the offer title).

Everything else is only read by the AI, to select the offers and write the documents.
The example below shows every key of a complete profile:

```jsonc
{
  "identity": {
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane.doe@example.com",
    "phone": "+33 6 00 00 00 00",
    "location": "Paris, France",
    "links": [
      { "label": "Portfolio", "url": "https://jane-doe.example.com" },
      { "label": "LinkedIn", "url": "https://www.linkedin.com/in/jane-doe" },
      { "label": "GitHub", "url": "https://github.com/jane-doe" },
    ],
  },
  "headline": "Backend developer",
  "summary": "Backend developer with 3 years of experience building high-traffic Python APIs.",
  "objectives": "Join a product team working on data and performance topics.",
  "experiences": [
    {
      "title": "Backend developer",
      "company": "Example Inc.",
      "company_description": "Logistics SaaS vendor",
      "contract": "Permanent",
      "location": "Paris",
      "start": "2023-01",
      "end": "present",
      "description": "Design and maintenance of the parcel tracking APIs.",
      "achievements": [
        "Cut the tracking API response time by 40% with a Redis cache.",
        "Set up CI/CD with GitLab CI and Docker.",
      ],
      "technologies": [
        "Python",
        "FastAPI",
        "PostgreSQL",
        "Redis",
        "Docker",
        "GitLab CI",
      ],
    },
  ],
  "projects": [
    {
      "name": "sync-tool",
      "date": "2024-06",
      "description": "Command line file synchronization tool.",
      "technologies": ["Go"],
      "url": "https://github.com/jane-doe/sync-tool",
    },
  ],
  "skills": [
    { "category": "Languages", "items": ["Python", "Go", "SQL"] },
    { "category": "Tools", "items": ["Docker", "PostgreSQL", "Redis", "Git"] },
  ],
  "education": [
    {
      "degree": "MSc Computer Science",
      "school": "Example University",
      "location": "Lyon",
      "start": "2020",
      "end": "2022",
      "description": "Distributed systems specialization.",
    },
  ],
  "spoken_languages": [
    { "language": "French", "level": "Native" },
    { "language": "English", "level": "Fluent (C1)" },
  ],
  "certifications": ["AWS Certified Cloud Practitioner (2024)"],
  "interests": ["Open source", "Climbing"],
  "preferences": {
    "target_roles": ["Backend Developer", "Software Engineer"],
    "locations": ["Paris", "Remote France"],
    "remote": "hybrid or full remote",
    "contract_types": ["Permanent (CDI)"],
    "seniority": "mid-level",
    "salary_min": "50k EUR gross per year",
    "availability": "Available immediately",
    "banned_keywords": ["PHP", "consulting firm"],
    "banned_title_keywords": ["internship", "apprenticeship"],
    "banned_companies": ["Evil Corp"],
    "notes": "No frequent business travel.",
  },
}
```

Anything not covered by these keys can be added freely: the AI reads the whole file.

## The configuration (`config.json`)

The configuration is not sent to the AI. Unknown keys are rejected.
The example below shows every key, with the default value of each one:

```jsonc
{
  "searches": [
    // one or more searches
    {
      "source": "linkedin", // see "Sources" below
      "keywords": "software engineer",
      "location": "Paris, Île-de-France, France",
      "max_results": 25, // offers scraped per search
      "posted_within": "day", // day | week | month | any
      "options": {}, // source specific settings, see "Sources"
    },
  ],
  "scraping": {
    "request_delay": 1.5, // seconds between two requests
    "cache_max_age_days": 7, // offer details older than this are downloaded again
    "francetravail": {
      // settings of the "francetravail" source, see "Sources"
      "client_id": "", // identifier of your francetravail.io application
      "client_secret_env": "A_JOBSEEKER_FRANCETRAVAIL_SECRET", // environment variable holding its secret
    },
  },
  "matching": {
    "min_score": 60, // minimum score to select an offer, see "How it works" below
    "report_language": "English", // language of the reason given for each score
  },
  "templates": {
    "cv": "classic", // see "Templates" below
    "cover_letter": "classic", // see "Templates" below
  },
  "ai": {
    "provider": "claude", // see "AI providers" below
    "path": null, // program path, defaults to the provider's program ("claude", "llm")
    "batch_size": 5, // offers evaluated per request
    "concurrency": 3, // requests running at the same time
    "timeout": 900, // seconds per request
    "max_attempts": 2, // attempts when the answer does not match the expected schema
    "claude": {
      // settings of the "claude" provider, used in this example
      "model": "sonnet", // see the "/model" list in the Claude Code interface
      "safe_mode": true, // ignores the user's CLAUDE.md, hooks, MCP servers...
      "max_budget_usd": null, // cost cap per request (float, e.g. 0.05, or null)
      "extra_args": [], // extra arguments passed to the "claude" program
    },
    "generic": {
      // settings of the "generic" provider, used when "--ai generic" is passed
      "args": [], // program arguments, "{prompt_file}" is replaced by the prompt file path
    },
  },
  "output": {
    "type": "stdout", // see "Outputs" below
    "email": {
      // settings of the "email" output, used when "--output email" is passed
      "smtp_host": "smtp.gmail.com", // SMTP server host
      "smtp_port": 587, // SMTP server port
      "username": "", // SMTP username, also used as the sender address
      "password_env": "A_JOBSEEKER_SMTP_PASSWORD", // environment variable holding the password
      "to": null, // recipient, defaults to identity.email from the profile
    },
  },
}
```

## Sources

### `linkedin`

Public (logged-out) LinkedIn job search pages, no account needed.
`location` is free text, as typed on LinkedIn.

`options` are raw LinkedIn search parameters, added to the query string:

```jsonc
"options": {
  "geoId": 105015875, // LinkedIn location id, more precise than "location"
  "distance": 25, // kilometers around the location
  "f_WT": "2,3", // workplace: 1 on-site, 2 remote, 3 hybrid
  "f_E": "2,3", // experience: 1 internship, 2 entry, 3 associate, 4 mid-senior, 5 director, 6 executive
  "f_JT": "F,C", // job type: F full-time, P part-time, C contract, T temporary, I internship, V volunteer, O other
  "f_C": "1035" // company id
}
```

### `welcometothejungle`

Public search index queried by the Welcome to the Jungle website, no account needed.
The descriptions come from its public API.

The first comma separated part of `location` is matched against the office city,
region or country code (`Paris`, `Ile-de-France`, `FR`).

`options`:

```jsonc
"options": {
  "language": "fr" // fr | en, language of the offer links
}
```

### `francetravail`

Official France Travail "Offres d'emploi v2" API: the France Travail offers,
and those of its partner job boards that agreed to share them (HelloWork, APEC, Cadremploi...).
A free account is needed:

1. Create an account on [francetravail.io](https://francetravail.io) and create an application.
2. Subscribe the application to the "Offres d'emploi v2" API (free).
3. Copy the application identifier to `scraping.francetravail.client_id`, and export its secret:

```bash
export A_JOBSEEKER_FRANCETRAVAIL_SECRET="..."
```

The first comma separated part of `location` is a French region, department or city name
(`Ile-de-France`, `Gironde`, `Nantes`), resolved to its code with
[geo.api.gouv.fr](https://geo.api.gouv.fr).
Paris, Lyon and Marseille are resolved to the codes the API accepts.

`options` are raw API parameters, overriding the ones built from the search:

```jsonc
"options": {
  "departement": "75,92", // up to 5 department codes, replaces "location"
  "commune": "44109", // INSEE city code, replaces "location"
  "region": "11", // region code, replaces "location"
  "distance": 20, // kilometers around "commune"
  "typeContrat": "CDI,CDD", // CDI, CDD, MIS (temping), SAI (seasonal), LIB (self-employed)...
  "experience": "2", // 1 less than 1 year, 2 from 1 to 3 years, 3 more than 3 years
  "tempsPlein": true, // true full-time, false part-time
  "qualification": 9, // 0 non-executive, 9 executive ("cadre")
  "salaireMin": 45000 // with "periodeSalaire": "A" (yearly), "M" (monthly), "H" (hourly)
}
```

The API returns at most 1150 offers per search: narrow the search (keywords, location,
`posted_within`) rather than raising `max_results` beyond.

Indeed is not supported: its pages are protected against automated access,
and it has no job search API.

## AI providers

- `claude` (default): Claude Code in print mode, with native JSON schema validated output.

- `generic`: any command line AI. The full prompt, including the expected JSON schema,
  is written to the program's stdin, or to a temporary file when an argument contains `{prompt_file}`.
  The JSON object is extracted from its output.

```bash
# e.g. with the "llm" CLI (https://llm.datasette.io), which reads the prompt from stdin
a-jobseeker run --ai generic --ai-path llm
```

```jsonc
// e.g. a program taking the prompt as a file argument
// replace "{prompt_file}" with the path of the prompt file
"ai": {
    "provider": "generic",
    "path": "/usr/local/bin/my-ai",
    "generic": { "args": ["--input", "{prompt_file}"] }
}
```

Whatever the provider, answers are validated against the expected schema,
and retried (`max_attempts`) with the validation errors when they do not match.

## Outputs

### `stdout`

Prints the text report shown in [Quick start](#quick-start), listing every matching offer
with its score, the reason of this score, its application link and the path of its documents.
No setting.

### `email`

Sends a single email listing every matching offer, with the documents attached.
Its settings are read from `output.email` (see [The configuration](#the-configuration-configjson)).

The connection is always encrypted: implicit TLS on port 465, STARTTLS on any other port.
The program only authenticates when `username` is set, and that address is then used as the sender.

With Gmail, the account password is refused: create an
[app password](https://myaccount.google.com/apppasswords) instead,
and export it under the name given by `password_env`:

```bash
export A_JOBSEEKER_SMTP_PASSWORD="..."
```

```bash
a-jobseeker run --output email
```

No email is sent when no new offer matches the profile.

## Scheduled runs

To receive the new matching offers by email twice a day,
run `a-jobseeker run --output email` with a systemd user timer.
Offers already evaluated are skipped (see [Files and directories](#files-and-directories)),
so each email only lists new offers.

The secrets go in a file only readable by you, one `NAME=value` per line:

```bash
# ~/.config/a-jobseeker/secrets.env
A_JOBSEEKER_SMTP_PASSWORD=...
A_JOBSEEKER_FRANCETRAVAIL_SECRET=...
CLAUDE_CODE_OAUTH_TOKEN=... # printed by "claude setup-token", for a server without browser
```

```ini
# ~/.config/systemd/user/a-jobseeker.service
[Unit]
Description=a-jobseeker run
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
EnvironmentFile=%h/.config/a-jobseeker/secrets.env
# Programs installed by uv, pipx and the Claude Code installer live in ~/.local/bin.
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=%h/.local/bin/a-jobseeker run --output email -v
```

```ini
# ~/.config/systemd/user/a-jobseeker.timer
[Unit]
Description=a-jobseeker run at 8:00 and 20:00

[Timer]
OnCalendar=*-*-* 08,20:00:00 Europe/Paris
# Runs a missed schedule (server down or rebooting) as soon as possible.
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
chmod 600 ~/.config/a-jobseeker/secrets.env
loginctl enable-linger "$USER" # runs the timer even when you are logged out
systemctl --user daemon-reload
systemctl --user enable --now a-jobseeker.timer

systemctl --user list-timers a-jobseeker.timer # next runs
systemctl --user start a-jobseeker.service # runs it now
journalctl --user -u a-jobseeker.service # logs
```

## Templates

A template describes what the AI must write, and how it is rendered as a PDF.
The documents are always named `cv.pdf` and `cover-letter.pdf`.

The documents are written in the language of the offer, English or French for now.
That language is the one declared by the job board when it provides it,
otherwise it is detected from the offer text.
An offer written in another language gets English documents.

### CV `classic`

Single column, designed to be parsed correctly by ATS (applicant tracking systems used by recruiters):

- no table, image or icon; selectable text in reading order;
- standard PDF fonts, conventional section headings ("Professional Experience", "Education"...);
- bullets drawn as shapes (no garbage glyph in the extracted text), links displayed in plain text;
- PDF metadata filled in (title, author, keywords);
- layout automatically tightened when it makes the CV fit on one page.

Sections: professional title and summary, experiences, projects, technical skills, education,
languages, and optional additional sections (certifications, CTF...).

### Cover letter `classic`

One page, in the usual formal layout: sender contact details, company, place and date,
subject, salutation, three or four paragraphs and a closing formula.

## How it works

```
scrapers ──► filters ──► AI selection ──► PDF rendering ──► output
```

The sources are scraped at the same time, and the searches of each source one after the other.
Before the detail of an offer is downloaded, it is skipped if it was already evaluated,
if it is banned by the profile preferences, or if another search already found it.
Duplicates are detected by offer id, and by company and title across searches and sources
(case, accents and gender markers such as "(H/F)" are ignored).
The `scrape` command applies the same deduplication.

For each batch of offers, a single request is sent to the AI. It contains the profile,
the offers and the description of the selected CV and cover letter templates
(writing guidelines + JSON schema of the expected content).
Up to `ai.concurrency` requests run at the same time.
Everything before the offers is identical in every request, so the AI provider can reuse its prompt cache.

For each offer, the AI returns, through a structured output validated against this schema:
the decision, a score, a one sentence reason and, if the offer is selected,
the content of the CV and of the cover letter.

Each application is saved in `<data dir>/applications/<date>/<source>-<company>-<title>-<id>/`:
the CV, the cover letter and `application.json`
(offer + generated content, which can be edited and rendered again with `a-jobseeker render`).

## Development

```bash
python -m venv .venv && make
.venv/bin/a-jobseeker init
.venv/bin/a-jobseeker run

# ...edit the code, then
make check # formats, lints, type checks, and runs the tests
```

`make check` fails when the tests do not cover every line and branch of the code.

To publish a new version on PyPI:

1. Update `__version__` in `src/a_jobseeker/__init__.py`, and check the package with `make dist`.
2. Commit and push, then publish a GitHub release whose tag is the version prefixed by `v` (e.g. `v0.2.0`).
3. The `Publish` workflow runs the checks, builds the package and uploads it to PyPI.

| Extension             | Base class                             | Registry                                     |
| --------------------- | -------------------------------------- | -------------------------------------------- |
| Job board             | `JobScraper` (`scrapers/base.py`)      | `SCRAPERS` (`scrapers/__init__.py`)          |
| AI provider           | `AIBackend` (`ai/base.py`)             | `AI_BACKENDS` (`ai/__init__.py`)             |
| Output                | `Output` (`outputs/base.py`)           | `OUTPUTS` (`outputs/__init__.py`)            |
| CV template           | `CVTemplate` (`templates/base.py`)     | `CV_TEMPLATES` (`templates/__init__.py`)     |
| Cover letter template | `LetterTemplate` (`templates/base.py`) | `LETTER_TEMPLATES` (`templates/__init__.py`) |

- Every extension follows the same pattern: subclass the base class,
  then add it to the registry of the package.
  The user then selects it by name in the configuration.

- A CV or cover letter template defines a pydantic `content_model`,
  which describes the content the AI must write, and whose JSON schema and field descriptions
  are sent to the AI, short `instructions` and a `render` method.

- To add a language to the documents, create a `templates/locales/<code>.json` file.

## Disclaimer

Offers are collected from public pages and APIs of job boards whose terms of use may restrict automated access:
use the tool reasonably (moderate volumes, delay between requests).

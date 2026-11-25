# Security

## Reporting a problem

Please report security problems privately, not in a public issue: on GitHub, open the **Security** tab
of this repository and choose **Report a vulnerability**
(<https://github.com/brandonbtm29/Capillary-Flow-Porometry-Analyzer/security/advisories/new>). You'll get a
reply as soon as I can manage; this is a one-person lab project, so please allow a few days.

## What the app does and doesn't do

- It runs on your own computer and reads `.CFT` files from folders you open. It doesn't listen on any
  network port (the check that only one copy runs uses a local socket on this computer).
- What it sends over the internet: the update check asks GitHub for the latest release, and an update
  runs `git fetch` from this repository and, only if the dependencies changed, `pip install` from PyPI.
  The start-up check can be turned off in the update window.
- Updates come only from this repository's published releases. The app fast-forwards its git folder to
  the release's tag and refuses if any of its files were edited by hand.
- Your data, tags (`run_tags.csv`) and exports stay in your data folder. Nothing is uploaded.
- **Shared folders:** anyone who can write to the SyncThing data or settings folder can change the run
  tags and shared settings the app uses on every computer that shares them. Share those folders only
  with your own devices.
- **Exports:** text you typed (tags, field names, run names) that a spreadsheet would read as a formula
  starts with `'` in the CSV and Excel files.
- **Diagnostics** (*Settings > App > Copy Diagnostics*) shorten your home folder to `~` and blank anything that
  looks like a password or token.

## Checks

CI scans the whole git history for secrets with [gitleaks](https://github.com/gitleaks/gitleaks) on
every push. The repo holds code only: measurement data, CapRep exports and results never go in it.

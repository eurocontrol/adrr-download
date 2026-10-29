# adrr-download

Downloads the EUROCONTROL R&D Data Archive (ADRR) datasets from the
[PRISME data provision HMI](https://ext.eurocontrol.int/prisme_data_provision_hmi/)
without clicking through the web interface.

The script logs in to OneSky Online with your username and password and fetches
the archive's file list. It then downloads every file into `data/`, keeping the
server's monthly folder layout (e.g. `data/202408/Flights_20240801_20240831.csv.gz`).
The full archive is about 1,500 files and roughly 130 GB.

## Setup

Requires [uv](https://docs.astral.sh/uv/), which installs the Python dependencies
on first run.

```sh
cp credentials.example.yaml credentials.yaml
```

Fill in your OneSky Online username and password in `credentials.yaml`.
Git ignores this file. Accounts that need an RSA token passcode are not supported.

## Usage

```sh
uv run adrr.py                  # download everything not yet downloaded
uv run adrr.py --list           # show what would be downloaded, without downloading
uv run adrr.py --match '2024*'  # only paths matching a glob, e.g. 'FIR_*' or '*/Flights_*'
```

You can stop and restart a run at any time:

- Files download to a `.part` file and are renamed only when complete. Finished
  files are skipped on the next run.
- Each file gets the timestamp of the server's copy. A later run downloads files
  that changed on the server again, and picks up newly published months.
- Failed downloads are retried three times, logging in again in case the session
  expired. Anything still failing is listed at the end; run the script again to
  retry it.

## How it works

The HMI is an Angular app on top of a small REST backend. The script calls the
backend directly:

| Request | Purpose |
| --- | --- |
| `POST /auth4u/up` | OneSky Online login form; sets the session cookies |
| `GET /prisme_data_provision_backend/files` | JSON tree of all folders and files |
| `POST /prisme_data_provision_backend/files/download` | Body is a JSON array of file entries from the tree; returns the raw file |

The backend endpoints require the login session cookies. Without them, requests
are redirected to the sign-in page.

## Terms of use

By downloading you accept the ADRR terms of use, which the web interface asks you
to confirm before each download. The data is for research and development only.
You must not share or distribute it, and you must acknowledge EUROCONTROL as the
source.

# Contributing

Thanks for your interest in improving embodied-daily! Issues and pull requests are welcome.

## Development setup

The script uses only the Python standard library (Python 3.9+) plus the system `curl`, so there is nothing to install.

```bash
git clone https://github.com/HaoyunT/embodied-daily.git
cd embodied-daily
cp config.example.json config.json      # optional; defaults work without it
python3 embodied_daily.py --no-deliver  # fetch, curate and archive without pushing anything
python3 -m unittest discover -s tests -v
```

Set `ANTHROPIC_API_KEY` (or install the `claude` CLI) to exercise AI curation; without either, the script falls back to raw abstracts and keyword tags.

## Guidelines

- Keep the runtime dependency-free (standard library only) unless there is a strong reason.
- Never commit `config.json`, API keys, Bark keys or SMTP passwords. Add new secrets as environment variables and document them in the README.
- Add or update tests in `tests/` for parsing and rendering changes. CI runs the test suite on Python 3.9 and 3.12.
- New config options need a default in `DEFAULT_CONFIG`, an entry in `config.example.json`, and a row in the README table.
- Use short, imperative commit messages (e.g. `feat: add Slack delivery`, `fix: handle empty arXiv response`).

## Reporting bugs

Please include the command you ran, the relevant lines from `logs/stdout.log` / `logs/stderr.log` (or the Actions log), and your OS and Python version. Remove any keys from logs before posting.

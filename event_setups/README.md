# Event setup spreadsheets (examples)

Each event at a tournament gets one of these, filled in by its supervisor. The app works for any event; these files are examples, and the tests import every `.xlsx` in this folder.

| File | Shape |
|------|-------|
| `PUSO_2026_AP_event_setup.xlsx` | 54 bubble questions numbered 1–54, some multi-select, 60 of 200 points |
| `EXAMPLE_forensics_event_setup.xlsx` | Mostly free response: 11 bubble questions numbered with gaps (25, 45, 49, 57–63, 68–69), 3–5 options, half-point questions, 14 of 300 points. Structure copied from a real Forensics sheet; correct letters are made up. |

To start a new event, copy either file, then fill in the `Event` tab and one row per **bubble** question on the `Questions` tab. Free-response, identification and lab points are not listed; they go into `free_response_max`. Check it with:

```bash
cd backend
uv run python -m app.cli import-event ../event_setups/your_event.xlsx
```

## Teams list

`EXAMPLE_teams.csv` is a made-up list of 12 teams for trying the app. For a real tournament, make your own with the same two columns: `team_number,team_name`, one team per line (in Excel or Numbers: Save As → CSV). One list covers every event. Importing again updates names and adds new teams.

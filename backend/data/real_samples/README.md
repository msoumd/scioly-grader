# Real phone photos for testing the reader

Fake sheets (`python -m app.harness build`) are the main test set. Real photos are the check that the fakes are not too easy, and phase 4 reports real and fake results separately.

## Privacy

Everything in this folder is **git-ignored except this README and the `staff/` folder**.

- `staff/<EVENT>/`: sheets filled in by staff with made-up answers and made-up team numbers, safe to commit.
- Any other folder (e.g. `private/<EVENT>/`): photos of real student sheets. They stay on your computer and are never committed.

## Adding photos

1. Print a sheet: `uv run python -m app.cli make-sheet --from-xlsx ../event_setups/<file>.xlsx`, at 100% scale.
2. Fill it in with pencil the way students do. Include some light marks, an erased answer, a double mark, a tick or cross, and a team number.
3. Photograph it with a phone the way a grader would: on a desk, a bit tilted, normal room light.
4. Start a folder for that event (once):

   ```bash
   cd backend
   uv run python -m app.harness label-template --from-xlsx ../event_setups/<file>.xlsx --out data/real_samples/staff/<EVENT>
   ```

5. Put the photo in that folder (e.g. `0001.jpg`). Copy `TEMPLATE.json` to `0001.json` and edit it:
   - `sample_id`: `"0001"`
   - `marks`: the letters the student meant for each question, e.g. `"12": ["B"]`, `"9": ["C", "D"]`, or `[]` if blank. An erased answer is blank.
   - `team_marks`: the digits bubbled in each team-number column, e.g. `[[0], [7]]` for team 7.
   - Optionally `fill_styles`, e.g. `"12:B": "light"`, so the report can break accuracy down by mark type.

6. Check the labels with the oracle reader (it should score 100%):

   ```bash
   uv run python -m app.harness evaluate --dataset data/real_samples/staff/<EVENT> --reader oracle
   ```

From phase 4, run the same command with `--reader detector` to measure the real reader on these photos.

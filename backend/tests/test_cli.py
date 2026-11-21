"""End-to-end checks of the command-line tools: file in, database written, score out."""

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.cli import main, parse_marks
from app.db.models import Event, Team

BACKEND = Path(__file__).resolve().parents[1]
AP_FILE = BACKEND.parent / "event_setups" / "PUSO_2026_AP_event_setup.xlsx"
FIXTURES = Path(__file__).parent / "fixtures" / "event_setup"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1=A", {1: {"A"}}),
        ("1=A,2=B,C", {1: {"A"}, 2: {"B", "C"}}),
        ("1=a, 2=bc ,3=", {1: {"A"}, 2: {"B", "C"}, 3: set()}),
        ("10=E; 11=A,E", {10: {"E"}, 11: {"A", "E"}}),
    ],
)
def test_parse_marks(text: str, expected: dict[int, set[str]]) -> None:
    assert parse_marks(text) == expected


@pytest.mark.parametrize("text", ["", "A,B", "1=A,1=B", "1=A, 9", "1=A 2"])
def test_parse_marks_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_marks(text)


def _sessions(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_import_event_check_only_does_not_write(
    migrated_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["import-event", str(AP_FILE)], _sessions(migrated_engine)) == 0
    out = capsys.readouterr().out
    assert "Result: OK" in out and "Checked only" in out
    with Session(migrated_engine) as s:
        assert s.scalars(select(Event)).first() is None


def test_import_save_then_score(
    migrated_engine: Engine, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    sessions = _sessions(migrated_engine)
    assert main(["import-event", str(AP_FILE), "--save"], sessions) == 0
    assert "Saved new event: AP (54 questions)" in capsys.readouterr().out

    # q1 key D, q9 key C,D, q11 key D (2 pts), q17 key B,D (2 pts) marked wrong
    assert main(["score-demo", "AP", "1=D,9=C,D,11=D,17=B"], sessions) == 0
    out = capsys.readouterr().out
    assert "Total: 4.00 / 60" in out
    assert "Unanswered: 50 question(s)" in out

    # Re-import before any scans: allowed, replaces questions
    assert main(["import-event", str(AP_FILE), "--save"], sessions) == 0
    assert "Replaced questions" in capsys.readouterr().out

    teams = tmp_path / "teams.csv"
    teams.write_bytes(b"\xef\xbb\xbfteam_number,team_name\n1,Alpha\n2,Beta\n")
    assert main(["import-teams", str(teams), "--save"], sessions) == 0
    assert "Saved teams: 2 new, 0 updated" in capsys.readouterr().out
    with Session(migrated_engine) as s:
        assert len(s.scalars(select(Team)).all()) == 2


def test_broken_event_exits_1(migrated_engine: Engine, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["import-event", str(FIXTURES / "many_problems.xlsx"), "--save"],
                _sessions(migrated_engine))  # fmt: skip
    assert code == 1
    assert "FAILED - 3 problems" in capsys.readouterr().out


def test_score_demo_unknown_event(
    migrated_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["score-demo", "NOPE", "1=A"], _sessions(migrated_engine)) == 1
    assert "No event with event_id 'NOPE'" in capsys.readouterr().out


def test_score_demo_bad_marks(migrated_engine: Engine, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["score-demo", "AP", "A,B"], _sessions(migrated_engine)) == 2


def test_database_not_migrated(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    assert main(["import-event", str(AP_FILE), "--save"], _sessions(engine)) == 1
    assert "Run: uv run alembic upgrade head" in capsys.readouterr().out


def test_runs_as_module() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "app.cli", "import-event", str(AP_FILE)],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Questions: 54" in proc.stdout

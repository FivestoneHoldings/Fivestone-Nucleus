import os
import subprocess
import sys


def test_postgresql_url_uses_installed_psycopg_driver():
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql://user:pass@localhost:5432/gateway"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.db import engine; print(engine.dialect.driver)",
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "psycopg"

import subprocess
import sys

from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    command = [sys.executable, "-m", "reflex", "run"]
    result = subprocess.run(command, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

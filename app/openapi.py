"""Export the OpenAPI specification of the service.

    python -m app.openapi -o docs.json
"""

import argparse
import json
import sys
from pathlib import Path

from app.main import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.openapi", description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--output", type=Path, help="output file (default: stdout)")
    args = parser.parse_args(argv)

    spec = json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(spec, encoding="utf-8")
    else:
        sys.stdout.buffer.write(spec.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

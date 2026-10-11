"""Thin caller for the package CLI; run with the isolated Hachi environment."""

from hachi.evaluation.case_study.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())

from pathlib import Path

import pytest

from core.security import safe_filename, safe_join, validate_guid


def test_validate_guid():
    assert validate_guid("AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA") == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    for bad in ["", "../etc", "1; DROP TABLE x", None]:
        with pytest.raises(ValueError):
            validate_guid(bad)


def test_safe_paths(tmp_path: Path):
    assert safe_filename("../../evil name?.png") == "evil_name_.png"
    p = safe_join(tmp_path, "..", "x.txt")
    assert tmp_path.resolve() in p.parents

"""Tests for iembot __init__.py."""

import iembot


def test_version():
    """Test that version is set."""
    assert iembot.__version__ is not None
    assert isinstance(iembot.__version__, str)
    # Should be either 'dev' or a version string with -dev suffix
    assert "dev" in iembot.__version__ or iembot.__version__[0].isdigit()

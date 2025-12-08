"""Tests for iembot atworker module."""

from unittest import mock

from iembot.atworker import ATManager


def test_atmanager_add_client():
    """Test ATManager add_client."""
    manager = ATManager()
    with mock.patch("iembot.atworker.ATWorkerThead") as mock_thread:
        mock_instance = mock.Mock()
        mock_thread.return_value = mock_instance
        manager.add_client("test.bsky.social", "password123")
        mock_thread.assert_called_once()
        mock_instance.start.assert_called_once()
        assert "test.bsky.social" in manager.at_clients


def test_atmanager_add_client_duplicate():
    """Test ATManager doesn't add duplicate clients."""
    manager = ATManager()
    manager.at_clients["test.bsky.social"] = mock.Mock()
    with mock.patch("iembot.atworker.ATWorkerThead") as mock_thread:
        manager.add_client("test.bsky.social", "password123")
        mock_thread.assert_not_called()


def test_atmanager_submit():
    """Test ATManager submit."""
    manager = ATManager()
    mock_queue = mock.Mock()
    mock_thread = mock.Mock()
    mock_thread.queue = mock_queue
    manager.at_clients["test.bsky.social"] = mock_thread

    manager.submit("test.bsky.social", {"msg": "Hello"})
    mock_queue.put.assert_called_once_with({"msg": "Hello"})

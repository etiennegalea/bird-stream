from controllers.peer_count_controller import ViewerRegistry


def test_counts_only_connections_marked_as_viewing():
    registry = ViewerRegistry()
    first = object()
    second = object()
    registry.connect(first)
    registry.connect(second)

    assert registry.count == 0
    assert registry.set_viewing(first, True)
    assert registry.count == 1
    assert not registry.set_viewing(first, True)
    assert registry.count == 1


def test_disconnect_removes_active_viewer():
    registry = ViewerRegistry()
    socket = object()
    registry.connect(socket)
    registry.set_viewing(socket, True)

    assert registry.disconnect(socket)
    assert registry.count == 0


def test_non_viewing_disconnect_does_not_change_count():
    registry = ViewerRegistry()
    socket = object()
    registry.connect(socket)

    assert not registry.disconnect(socket)
    assert registry.count == 0

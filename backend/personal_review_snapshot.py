"""Reuse the foundation's bounded, no-source-SQLite private-image reader."""
from contextlib import closing
from pathlib import Path
import fact_lake_store as foundation


class Snapshot:
    def __init__(self, path):
        self.path = Path(path)
        if any(foundation._is_link_or_reparse(p) for p in (self.path, *self.path.parents)):
            raise ValueError("unsafe local review source path")
        if not self.path.exists() and any(Path(str(self.path) + suffix).exists() or foundation._is_link_or_reparse(Path(str(self.path) + suffix)) for suffix in ("-wal", "-shm", "-journal")):
            raise ValueError("orphan local review source journal")
        self.source = foundation._ControlSnapshot(self.path) if self.path.exists() else None

    def read(self, reader, empty):
        if self.source is None:
            return empty
        with closing(self.source.connect()) as conn:
            result = reader(conn)
        self.assert_unchanged()
        return result

    def assert_unchanged(self):
        if self.source:
            self.source.assert_unchanged()
        elif self.path.exists() or any(foundation._is_link_or_reparse(p) for p in (self.path, *self.path.parents)):
            raise ValueError("local review source appeared during read")

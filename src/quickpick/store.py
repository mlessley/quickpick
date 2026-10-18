from dataclasses import dataclass


@dataclass(frozen=True)
class StoreEntry:
    key: str
    value: str
    masked: bool

    @property
    def display_text(self) -> str:
        if self.masked:
            return self.key
        return f"{self.key}: {self.value}"


SEPARATOR = "~!~"


def parse_store(text: str) -> list[StoreEntry]:
    entries = []
    for line in text.splitlines():
        if not line:
            continue
        key, _, value = line.partition(SEPARATOR)
        masked = key.startswith("*")
        if masked:
            key = key[1:]
        entries.append(StoreEntry(key=key, value=value, masked=masked))
    return entries


def filter_entries(entries: list[StoreEntry], query: str) -> list[StoreEntry]:
    needle = query.lower()
    return [entry for entry in entries if needle in entry.display_text.lower()]

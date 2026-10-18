from dataclasses import dataclass


@dataclass(frozen=True)
class QuickCopyEntry:
    key: str
    value: str
    masked: bool

    @property
    def display_text(self) -> str:
        if self.masked:
            return self.key
        return f"{self.key}: {self.value}"


def parse_store(text: str) -> list[QuickCopyEntry]:
    entries = []
    for line in text.splitlines():
        if not line:
            continue
        key, _, value = line.partition("~!~")
        masked = key.startswith("*")
        if masked:
            key = key[1:]
        entries.append(QuickCopyEntry(key=key, value=value, masked=masked))
    return entries


def filter_entries(entries: list[QuickCopyEntry], query: str) -> list[QuickCopyEntry]:
    needle = query.lower()
    return [entry for entry in entries if needle in entry.display_text.lower()]

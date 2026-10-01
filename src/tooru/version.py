import re

__version__ = "0.0.16"


def display_version(value: str = __version__) -> str:
    parts = [int(part) for part in re.findall(r"\d+", value)[:3]]
    while len(parts) < 3:
        parts.append(0)
    return ".".join(f"{part:02d}" for part in parts)


APP_VERSION = display_version()

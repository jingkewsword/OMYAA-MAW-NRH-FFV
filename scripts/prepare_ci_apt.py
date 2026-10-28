"""Bound Ubuntu CI package downloads without changing repository trust settings."""
from pathlib import Path
import re


# Match complete known Ubuntu archive URLs, not third-party hosts or path prefixes.
UBUNTU_ARCHIVE = re.compile(
    r"(?<!\S)https?://(azure\.archive|archive|security)\.ubuntu\.com/ubuntu/?(?=\s|$)"
)
APT_POLICY = '''Acquire::Retries "2";
Acquire::http::Timeout "30";
Acquire::https::Timeout "30";
APT::Install-Recommends "false";
'''


def official_https(text: str) -> str:
    def replace(match: re.Match) -> str:
        host = "security" if match[1] == "security" else "archive"
        return f"https://{host}.ubuntu.com/ubuntu/"

    return UBUNTU_ARCHIVE.sub(replace, text)


def configure(apt: Path) -> None:
    sources = [apt / "sources.list", apt / "apt-mirrors.txt"]
    sources.extend(sorted((apt / "sources.list.d").glob("*.list")))
    sources.extend(sorted((apt / "sources.list.d").glob("*.sources")))
    for path in sources:
        if path.is_file():
            original = path.read_text(encoding="utf-8")
            updated = official_https(original)
            if updated != original:
                path.write_text(updated, encoding="utf-8", newline="\n")
                print(f"Selected official Ubuntu HTTPS archive: {path.name}")
    (apt / "apt.conf.d" / "99-maw-ci-downloads").write_text(
        APT_POLICY, encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    configure(Path("/etc/apt"))

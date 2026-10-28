"""Ubuntu CI preparation preserves repository boundaries and signature settings."""
from pathlib import Path
import tempfile
import unittest

from scripts.prepare_ci_apt import APT_POLICY, configure, official_https


class PrepareCiAptTests(unittest.TestCase):
    def test_changes_only_complete_known_ubuntu_archive_urls(self):
        source = (
            "deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] "
            "http://azure.archive.ubuntu.com/ubuntu noble main\n"
            "URIs: http://archive.ubuntu.com/ubuntu/ https://security.ubuntu.com/ubuntu\n"
        )
        expected = source.replace("http://azure.archive.ubuntu.com/ubuntu", "https://archive.ubuntu.com/ubuntu/")
        expected = expected.replace("http://archive.ubuntu.com/ubuntu/", "https://archive.ubuntu.com/ubuntu/")
        expected = expected.replace("https://security.ubuntu.com/ubuntu\n", "https://security.ubuntu.com/ubuntu/\n")
        self.assertEqual(official_https(source), expected)
        unrelated = (
            "deb https://packages.microsoft.com/repos/code stable main\n"
            "URIs: mirror+file:/etc/apt/apt-mirrors.txt\n"
            "http://azure.archive.ubuntu.com.example/ubuntu\n"
            "http://archive.ubuntu.com/ubuntu-extra\n"
        )
        self.assertEqual(official_https(unrelated), unrelated)

    def test_configures_both_source_formats_and_runner_mirror_list(self):
        with tempfile.TemporaryDirectory() as temp:
            apt = Path(temp)
            (apt / "sources.list.d").mkdir()
            (apt / "apt.conf.d").mkdir()
            paths = [apt / "sources.list", apt / "apt-mirrors.txt",
                     apt / "sources.list.d" / "ubuntu.list", apt / "sources.list.d" / "ubuntu.sources"]
            source = "URIs: http://azure.archive.ubuntu.com/ubuntu/\nSigned-By: ubuntu-keyring.gpg\n"
            for path in paths:
                path.write_text(source, encoding="utf-8")
            third_party = apt / "sources.list.d" / "vendor.sources"
            vendor = "URIs: https://packages.example.org/ubuntu\nSigned-By: vendor.gpg\n"
            third_party.write_text(vendor, encoding="utf-8")
            configure(apt)
            for path in paths:
                self.assertEqual(path.read_text(encoding="utf-8"), official_https(source))
            self.assertEqual(third_party.read_text(encoding="utf-8"), vendor)
            policy = apt / "apt.conf.d" / "99-maw-ci-downloads"
            self.assertEqual(policy.read_text(encoding="utf-8"), APT_POLICY)
            self.assertNotIn("AllowUnauthenticated", APT_POLICY)
            self.assertNotIn("Verify-Peer", APT_POLICY)
            configure(apt)
            self.assertEqual(policy.read_text(encoding="utf-8"), APT_POLICY)

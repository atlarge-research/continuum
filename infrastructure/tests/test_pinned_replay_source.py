"""Opt-in checks against the fetched immutable source, not a network download."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PATCH = (
    Path(__file__).resolve().parents[1] / "qemu/infrastructure/packet-match-stack.patch"
)


@unittest.skipUnless(
    os.environ.get("FNS_MAHIMAHI_SOURCE"), "requires pinned source checkout"
)
class PinnedSourceTests(unittest.TestCase):
    def test_address_matcher_preserves_bypass_without_per_packet_heap_growth(self):
        self.assertTrue(PATCH.exists(), "packet matcher compatibility patch is missing")
        source = Path(os.environ["FNS_MAHIMAHI_SOURCE"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "src/frontend"
            directory.mkdir(parents=True)
            shutil.copyfile(
                source / "src/frontend/link_queue.cc", directory / "link_queue.cc"
            )
            subprocess.run(
                ["patch", "--batch", "-p1", "-i", str(PATCH)],
                cwd=root,
                check=True,
                capture_output=True,
            )
            content = (directory / "link_queue.cc").read_text()
            matcher = content[
                content.index("const size_t ETHERNET_HEADER_LEN") : content.index(
                    "LinkQueue::LinkQueue"
                )
            ]
            harness = (
                r"""
#include <string>
#include <cstring>
#include <cstdlib>
#include <cstdint>
#include <iostream>
#include <malloc.h>
#include <arpa/inet.h>
using namespace std;
"""
                + matcher
                + r"""
size_t allocated() {
#if __GLIBC_PREREQ(2, 33)
    return mallinfo2().uordblks;
#else
    return mallinfo().uordblks;
#endif
}
int main() {
    string packet(24, '\0');
    char ignored[] = "10.0.0.1";
    in_addr address;
    inet_pton(AF_INET, ignored, &address);
    memcpy(&packet[16], &address.s_addr, 4);
    if (!match_address(ignored, ignored, packet)) return 2;
    packet.assign(24, '\0');
    memcpy(&packet[20], &address.s_addr, 4);
    if (!match_address(ignored, ignored, packet)) return 3;
    packet.assign(24, '\0');
    if (match_address(ignored, ignored, string(5, '\0'))) return 4;
    auto before = allocated();
    for (int i=0; i<100000; ++i) {
        if (match_address(ignored, ignored, packet)) return 5;
    }
    auto retained = allocated() - before;
    cout << retained << endl;
    return retained > 131072 ? 1 : 0;
}
"""
            )
            (root / "matcher.cc").write_text(harness)
            subprocess.run(
                [
                    "g++",
                    "-std=c++11",
                    "-O0",
                    str(root / "matcher.cc"),
                    "-o",
                    str(root / "matcher"),
                ],
                check=True,
                capture_output=True,
            )
            result = subprocess.run(
                [str(root / "matcher")], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

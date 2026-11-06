"""System libvirt ownership and teardown regressions."""

from pathlib import PurePosixPath
import unittest
from unittest import mock
from xml.etree import ElementTree

from infrastructure.machine import Machine
from infrastructure.qemu import qemu


OWN = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
ROOT = "/slot"
IMAGES = "/slot/.continuum/images"


def _domain(uuid, name, root=IMAGES):
    return (
        f"<domain><name>{name}</name><uuid>{uuid}</uuid><devices>"
        f'<disk type="file" device="disk"><source file="{root}/{name}.qcow2"/>'
        '<target dev="vda"/></disk>'
        f'<disk type="file" device="disk"><source file="{root}/user_data_{name}.img"/>'
        '<target dev="vdb"/></disk></devices></domain>'
    )


class QemuCleanupTests(unittest.TestCase):
    def setUp(self):
        self.config = {"username": "alice", "infrastructure": {"base_path": ROOT}}
        self.owner = Machine("alice@worker.local", False)
        self.owner.cloud_names = ["cloud0_alice"]

    def _inventory(
        self, domains, *, persistent=(), destroy_error=None, retain=False, foreign_roots=(),
        unreadable_roots=(),
    ):
        def process(_config, argv, **_kwargs):
            if argv[0] == "realpath":
                return [[list(map(str, map(PurePosixPath, argv[3:]))), []]]
            if argv == ["id", "-u"]:
                return [[["1004"], []]]
            if argv[:2] == ["sh", "-c"]:
                uids = {path: "1002" for path in foreign_roots}
                uids.update({path: "?" for path in unreadable_roots})
                return [[[uids.get(path, "1004") for path in argv[4:]], []]]
            self.assertEqual(argv[:3], ["virsh", "--connect", "qemu:///system"])
            operation, *args = argv[3:]
            if operation == "list":
                if "--name" in args:
                    return [[[ElementTree.fromstring(xml).findtext("name")
                              for xml in domains.values()], []]]
                return [[[uuid for uuid in domains if "--transient" not in args
                          or uuid not in persistent], []]]
            if operation == "dumpxml":
                return [[[domains[args[-1]]], []]]
            if operation == "domuuid":
                return [[[uuid for uuid, xml in domains.items()
                          if ElementTree.fromstring(xml).findtext("name") == args[0]], []]]
            if operation == "destroy":
                if destroy_error:
                    return [[[], [destroy_error]]]
                if not retain:
                    del domains[args[0]]
                return [[[], []]]
            self.fail(f"Unexpected libvirt command: {argv}")
        return mock.patch.object(self.owner, "process_on_owner", side_effect=process)

    def test_startup_destroys_only_domains_owned_by_the_physical_login(self):
        domains = {
            OWN: _domain(OWN, "cloud0_alice"),
            OTHER: _domain(OTHER, "cloud0_alice2", "/another/.continuum/images"),
        }
        with self._inventory(domains, foreign_roots=["/another/.continuum"]) as process:
            qemu.cleanup_startup(self.config, [self.owner])
        self.assertEqual(set(domains), {OTHER})
        destroy = [c.args[1] for c in process.call_args_list if "destroy" in c.args[1]]
        self.assertEqual(destroy, [["virsh", "--connect", "qemu:///system", "destroy", OWN]])

    def test_startup_fails_before_destroy_on_protected_planned_name(self):
        domains = {OTHER: _domain(OTHER, "cloud0_alice", "/another/.continuum/images")}
        with (
            self._inventory(domains, foreign_roots=["/another/.continuum"]) as process,
            self.assertRaisesRegex(RuntimeError, "cloud0_alice"),
        ):
            qemu.cleanup_startup(self.config, [self.owner])
        self.assertFalse(any("destroy" in c.args[1] for c in process.call_args_list))

    def test_startup_reclaims_old_workspace_with_and_without_name_collision(self):
        for name in ("cloud0_alice", "edge3_previous_launcher"):
            with self.subTest(name=name):
                domains = {OWN: _domain(OWN, name, "/old/.continuum/images")}
                with self._inventory(domains) as process:
                    qemu.cleanup_startup(self.config, [self.owner])
                self.assertEqual(domains, {})
                self.assertFalse(any(c.args[1][0] in ("rm", "unlink") for c in process.call_args_list))

    def test_startup_preserves_a_pair_redirected_to_another_workspace(self):
        domains = {OTHER: _domain(OTHER, "edge3_alice", "/old/.continuum/images")}
        with self._inventory(domains) as process:
            original = process.side_effect

            def resolve(_config, argv, **kwargs):
                if argv[0] == "realpath":
                    return [[[path.replace("/old/", "/elsewhere/") if path.endswith(
                        (".qcow2", ".img")
                    ) else path for path in argv[3:]], []]]
                return original(_config, argv, **kwargs)

            process.side_effect = resolve
            qemu.cleanup_startup(self.config, [self.owner])
        self.assertIn(OTHER, domains)

    def test_startup_preserves_unreadable_old_workspace_without_collision(self):
        domains = {
            OWN: _domain(OWN, "cloud0_alice", "/old/.continuum/images"),
            OTHER: _domain(OTHER, "edge3_other", "/private/.continuum/images"),
        }
        with self._inventory(domains, unreadable_roots=["/private/.continuum"]):
            qemu.cleanup_startup(self.config, [self.owner])
        self.assertEqual(set(domains), {OTHER})

    def test_startup_preserves_a_workspace_redirected_into_another_base(self):
        domains = {OTHER: _domain(OTHER, "edge3_alice", "/old/.continuum/images")}
        with self._inventory(domains) as process:
            original = process.side_effect

            def resolve(_config, argv, **kwargs):
                if argv[0] == "realpath":
                    return [[[path.replace("/old/", "/elsewhere/") for path in argv[3:]], []]]
                return original(_config, argv, **kwargs)

            process.side_effect = resolve
            qemu.cleanup_startup(self.config, [self.owner])
        self.assertIn(OTHER, domains)

    def test_final_teardown_rejects_nonzero_or_still_present(self):
        for error in ("Permission denied", None):
            with self.subTest(error=error):
                domains = {OWN: _domain(OWN, "cloud0_alice")}
                with (
                    self._inventory(domains, destroy_error=error, retain=True),
                    mock.patch.object(self.owner, "process", side_effect=AssertionError),
                    self.assertRaisesRegex(RuntimeError, "worker.local"),
                ):
                    qemu.delete_vms(self.config, [self.owner])

    def test_persistent_definition_in_workspace_blocks_startup(self):
        domains = {OTHER: _domain(OTHER, "unrelated")}
        with (
            self._inventory(domains, persistent=[OTHER]) as process,
            self.assertRaisesRegex(RuntimeError, "Protected.*unrelated"),
        ):
            qemu.cleanup_startup(self.config, [self.owner])
        self.assertTrue(any("--inactive" in c.args[1] for c in process.call_args_list))
        self.assertFalse(any("destroy" in c.args[1] for c in process.call_args_list))

    def test_failed_inventory_on_second_owner_prevents_first_destroy(self):
        second = Machine("alice@second", False)
        domains = {OWN: _domain(OWN, "cloud0_alice")}
        with (
            self._inventory(domains) as process,
            mock.patch.object(second, "process_on_owner", return_value=[[[], ["unreachable"]]]),
            self.assertRaisesRegex(RuntimeError, "second.*unreachable"),
        ):
            qemu.cleanup_startup(self.config, [self.owner, second])
        self.assertFalse(any("destroy" in c.args[1] for c in process.call_args_list))

    def test_final_teardown_leaves_other_same_root_names_to_startup(self):
        domains = {
            OWN: _domain(OWN, "cloud0_alice"),
            OTHER: _domain(OTHER, "edge0_alice"),
        }
        with self._inventory(domains):
            qemu.delete_vms(self.config, [self.owner])
        self.assertEqual(set(domains), {OTHER})

    def test_owner_resolves_dotdot_after_the_symlink_component(self):
        self.config["infrastructure"]["base_path"] = "/slot/link/../run"
        raw_root = "/slot/link/../run/.continuum/images"
        canonical = "/other/run/.continuum/images"
        domains = {OTHER: _domain(OTHER, "cloud0_alice", "/slot/run/.continuum/images")}
        with self._inventory(domains, foreign_roots=["/slot/run/.continuum"]) as process:
            original = process.side_effect

            def resolve(_config, argv, **kwargs):
                if argv[0] == "realpath":
                    self.assertEqual(argv[4], raw_root)
                    return [[["/other/run", canonical, *argv[5:]], []]]
                return original(_config, argv, **kwargs)

            process.side_effect = resolve
            with self.assertRaisesRegex(RuntimeError, "Protected.*cloud0_alice"):
                qemu.cleanup_startup(self.config, [self.owner])
        self.assertFalse(any("destroy" in c.args[1] for c in process.call_args_list))

    def test_symlinked_image_directory_does_not_authorize_another_base(self):
        domains = {OTHER: _domain(OTHER, "cloud0_alice", "/another/.continuum/images")}
        with self._inventory(domains) as process:
            original = process.side_effect

            def resolve(_config, argv, **kwargs):
                if argv[0] == "realpath":
                    return [[[ROOT, "/another/.continuum/images", *argv[5:]], []]]
                return original(_config, argv, **kwargs)

            process.side_effect = resolve
            with self.assertRaisesRegex(RuntimeError, "resolves outside"):
                qemu.cleanup_startup(self.config, [self.owner])
        self.assertFalse(any("destroy" in c.args[1] for c in process.call_args_list))

    def test_protected_storage_volume_reference_blocks_startup(self):
        domains = {
            OTHER: _domain(OTHER, "unrelated").replace(
                f'file="{IMAGES}/unrelated.qcow2"', 'pool="test" volume="another"',
            ).replace(f'{IMAGES}/user_data_unrelated.img', '/external/seed.img')
        }
        with self._inventory(domains) as process:
            original = process.side_effect

            def resolve(_config, argv, **kwargs):
                if "vol-path" in argv:
                    self.assertEqual(argv[-2:], ["--pool=test", "--vol=another"])
                    return [[[f"{IMAGES}/cloud_data.qcow2"], []]]
                return original(_config, argv, **kwargs)

            process.side_effect = resolve
            with self.assertRaisesRegex(RuntimeError, "Protected.*unrelated"):
                qemu.cleanup_startup(self.config, [self.owner])
        self.assertFalse(any("destroy" in c.args[1] for c in process.call_args_list))

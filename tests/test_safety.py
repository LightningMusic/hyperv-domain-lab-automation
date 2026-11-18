"""
Offline tests of the safety logic (no Hyper-V, no PowerShell, no VMs).

Run from the project root:   python -m unittest discover -s tests -t . -v
"""
import unittest
import xml.dom.minidom

import config_loader as cl
from core import ownership
from core import preflight, teardown
from utils.powershell_runner import redact


class ContainmentTests(unittest.TestCase):
    def test_relative_path_resolves_inside_project(self):
        self.assertTrue(cl._abs("LabVMs").startswith(str(cl.PROJECT_ROOT)))

    def test_absolute_path_elsewhere_is_rejected(self):
        with self.assertRaises(cl.ConfigError):
            cl._abs(r"C:\Windows\Temp\evil")

    def test_dotdot_escape_is_rejected(self):
        with self.assertRaises(cl.ConfigError):
            cl._abs(r"..\..\somewhere")

    def test_absolute_path_inside_project_is_allowed(self):
        inside = str(cl.PROJECT_ROOT / "LabVMs")
        self.assertEqual(cl._abs(inside), inside)

    def test_shipped_config_paths_are_all_inside_project(self):
        for p in (cl.get_lab_root(), cl.get_unattend_dir(), cl.get_log_dir(),
                  cl.get_server_iso(), cl.get_win11_iso()):
            self.assertTrue(cl.is_within_project(p), p)

    def test_assert_inside_project(self):
        ownership.assert_inside_project(cl.PROJECT_ROOT / "LabVMs" / "x.vhdx")
        with self.assertRaises(ownership.OwnershipError):
            ownership.assert_inside_project(r"D:\Anything\else.vhdx")


class OwnershipTests(unittest.TestCase):
    def test_tag_must_be_exact_token(self):
        t = ownership.tag()
        self.assertTrue(ownership.is_ours(f"{t} kind=vm"))
        self.assertTrue(ownership.is_ours(t))
        self.assertFalse(ownership.is_ours(f"{t}2 kind=vm"))     # different lab id
        self.assertFalse(ownership.is_ours(f"prefix {t}"))       # tag not at start
        self.assertFalse(ownership.is_ours(""))
        self.assertFalse(ownership.is_ours(None))
        self.assertFalse(ownership.is_ours("some other tool's note"))

    def test_note_round_trips(self):
        self.assertTrue(ownership.is_ours(ownership.note("vm")))

    def test_only_configured_names_are_allowed(self):
        for name in ownership.lab_vm_names():
            ownership.assert_vm_allowed(name)
        for foreign in ("CcdcLab-DC", "SomeoneElsesVM", ""):
            with self.assertRaises(ownership.OwnershipError):
                ownership.assert_vm_allowed(foreign)
        with self.assertRaises(ownership.OwnershipError):
            ownership.assert_switch_allowed("Default Switch")


class RedactionTests(unittest.TestCase):
    def test_passwords_are_masked(self):
        for text in ('ConvertTo-SecureString "Hunter2!" -AsPlainText -Force',
                     "ConvertTo-SecureString 'Hunter2!' -AsPlainText -Force",
                     "<Value>Hunter2!</Value>"):
            self.assertNotIn("Hunter2!", redact(text), text)

    def test_none_and_empty_pass_through(self):
        self.assertIsNone(redact(None))
        self.assertEqual(redact(""), "")


class UnattendTests(unittest.TestCase):
    def setUp(self):
        import core.hyperv_manager as hv
        self.hv = hv
        self._orig = hv.ADMIN_PASS

    def tearDown(self):
        self.hv.ADMIN_PASS = self._orig

    def test_xml_is_well_formed_and_sets_name_and_edition(self):
        doc = xml.dom.minidom.parseString(self.hv._unattend_xml("AcmePDC01", 2))
        self.assertIn("AcmePDC01", [n.firstChild.data for n in doc.getElementsByTagName("ComputerName")])
        self.assertIn("2", [n.firstChild.data for n in doc.getElementsByTagName("Value")])

    def test_special_characters_in_password_are_escaped(self):
        self.hv.ADMIN_PASS = "a&b<c>\"'"
        xml.dom.minidom.parseString(self.hv._unattend_xml("AcmePDC01", 2))   # must not raise

    def test_every_role_has_an_install_profile(self):
        for vm in cl.get_vms():
            iso, flavor, idx = self.hv._install_profile(vm["role"])
            self.assertTrue(iso.endswith(".iso"))
            self.assertIn(flavor, ("server", "client"))
            self.assertGreaterEqual(idx, 1)


def _facts(**over):
    base = {"vmms": "Running", "freeMemGB": 40.0, "vms": [], "registered": [],
            "switches": [{"Name": "Default Switch", "Id": cl.get_uplink_switch_id(), "Type": "Internal", "Owned": False}],
            "ips": ["10.0.0.5/24"], "nats": []}
    base.update(over)
    return base


class PreflightTests(unittest.TestCase):
    def test_free_name_passes(self):
        res = preflight.check_vm_collisions(_facts(), ["AcmePDC01"])
        self.assertEqual(res[0].status, "PASS")

    def test_vm_with_our_tag_is_reused(self):
        facts = _facts(vms=[{"Name": "AcmePDC01", "State": "Off", "Owned": True}])
        self.assertEqual(preflight.check_vm_collisions(facts, ["AcmePDC01"])[0].status, "PASS")

    def test_vm_without_our_tag_fails(self):
        facts = _facts(vms=[{"Name": "AcmePDC01", "State": "Off", "Owned": False}])
        self.assertEqual(preflight.check_vm_collisions(facts, ["AcmePDC01"])[0].status, "FAIL")

    def test_ghost_record_fails_with_doctor_hint(self):
        facts = _facts(registered=[{"Name": "AcmePDC01", "Health": 25}])
        res = preflight.check_vm_collisions(facts, ["AcmePDC01"])[0]
        self.assertEqual(res.status, "FAIL")
        self.assertIn("doctor", res.detail)

    def test_foreign_switch_with_our_name_fails(self):
        sw = {"Name": cl.get_internal_switch(), "Id": "x", "Type": "Private", "Owned": False}
        facts = _facts(switches=_facts()["switches"] + [sw])
        self.assertEqual(preflight.check_switches(facts)[0].status, "FAIL")

    def test_non_private_own_switch_fails(self):
        sw = {"Name": cl.get_internal_switch(), "Id": "x", "Type": "Internal", "Owned": True}
        facts = _facts(switches=_facts()["switches"] + [sw])
        self.assertEqual(preflight.check_switches(facts)[0].status, "FAIL")

    def test_missing_uplink_switch_fails(self):
        self.assertEqual(preflight.check_switches(_facts(switches=[]))[-1].status, "FAIL")

    def test_subnet_overlap_with_host_ip_or_nat_fails(self):
        self.assertEqual(preflight.check_subnet_overlap(_facts(ips=["192.168.4.254/24"])).status, "FAIL")
        self.assertEqual(preflight.check_subnet_overlap(_facts(nats=["192.168.0.0/16"])).status, "FAIL")
        self.assertEqual(preflight.check_subnet_overlap(_facts()).status, "PASS")

    def test_not_enough_ram_fails(self):
        res = preflight.check_ram(_facts(freeMemGB=6.0), ["AcmeRtr01", "AcmePDC01", "AcmeWks1001"], 8)
        self.assertEqual(res.status, "FAIL")

    def test_shipped_vm_specs_meet_os_minimums(self):
        self.assertTrue(all(c.status == "PASS" for c in preflight.check_vm_specs()))

    def test_stopped_hyperv_fails(self):
        self.assertEqual(preflight.check_hyperv(_facts(vmms="Stopped")).status, "FAIL")


class TeardownPlanTests(unittest.TestCase):
    def test_only_tagged_objects_are_planned_and_others_are_skipped(self):
        facts = _facts(
            vms=[{"Name": "AcmeRtr01", "State": "Off", "Owned": True},     # ours
                 {"Name": "AcmePDC01", "State": "Off", "Owned": False},                       # same name, NOT ours
                 {"Name": "CcdcLab-DC", "State": "Off", "Owned": False}],                     # unrelated lab
            switches=[{"Name": cl.get_internal_switch(), "Id": "a", "Type": "Private", "Owned": True}],
        )
        plan = teardown.build_plan(facts)
        self.assertEqual(plan["vms"], ["AcmeRtr01"])
        self.assertEqual(plan["switches"], [cl.get_internal_switch()])
        self.assertTrue(any("AcmePDC01" in s for s in plan["skipped"]))
        self.assertFalse(any("Ccdc" in s for s in plan["skipped"] + plan["vms"]))

    def test_foreign_switch_is_never_planned(self):
        facts = _facts(switches=[{"Name": cl.get_internal_switch(), "Id": "a", "Type": "Internal", "Owned": False}])
        plan = teardown.build_plan(facts)
        self.assertEqual(plan["switches"], [])
        self.assertEqual(len(plan["skipped"]), 1)

    def test_ghosts_are_reported_not_removed_by_teardown(self):
        plan = teardown.build_plan(_facts(registered=[{"Name": "AcmePDC01", "Health": 25}]))
        self.assertEqual(plan["ghosts"], ["AcmePDC01"])
        self.assertEqual(plan["vms"], [])

    def test_dry_run_changes_nothing(self):
        import unittest.mock as m
        with m.patch.object(teardown, "build_plan", return_value={"vms": ["AcmeRtr01"], "switches": [],
                                                                  "skipped": [], "ghosts": []}), \
             m.patch.object(teardown, "_remove_vm") as rv, m.patch.object(teardown, "_remove_switch") as rs, \
             m.patch.object(teardown, "_clean_generated") as cg:
            teardown.teardown(dry_run=True)
            rv.assert_not_called(); rs.assert_not_called(); cg.assert_not_called()

    def test_wrong_confirmation_cancels(self):
        import unittest.mock as m
        with m.patch.object(teardown, "build_plan", return_value={"vms": ["AcmeRtr01"], "switches": [],
                                                                  "skipped": [], "ghosts": []}), \
             m.patch.object(teardown, "_remove_vm") as rv:
            teardown.teardown(input_fn=lambda _: "yes please")
            rv.assert_not_called()


if __name__ == "__main__":
    unittest.main()

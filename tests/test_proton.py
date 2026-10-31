"""Offline contract tests: no Proton client, login, or VPN calls required."""
from pathlib import Path
from unittest import TestCase, mock
import subprocess

from xvpn.proton import (ProtonStatus, is_proton_adapter, parse_adapters, parse_tasks,
                         find_proton_app, launch_proton_app, read_proton_status,
                         _candidate_paths, _folder_executables, PROTON_PROCESS_NAMES)


class ProtonStatusTests(TestCase):
    def test_non_proton_wg_is_not_falsely_claimed(self):
        self.assertFalse(is_proton_adapter('WireGuard Tunnel', 'Wintun Userspace Tunnel'))
        self.assertTrue(is_proton_adapter('ProtonVPN TUN', 'WireGuard Tunnel'))

    def test_readonly_adapter_json(self):
        data = ('[{"Name":"Wintun","InterfaceDescription":"Generic", "Status":"Up"},'
                '{"Name":"Proton VPN","InterfaceDescription":"ProtonVPN Adapter", "Status":"Up"}]')
        self.assertEqual(parse_adapters(data), (True, True, 'Proton VPN'))
        self.assertEqual(parse_adapters('[{"Name":"ProtonVPN", "Status":"Disconnected"}]'),
                         (True, False, 'ProtonVPN'))
        self.assertEqual(parse_adapters('[]'), (False, False, ''))

    def test_process_name_must_match_exactly(self):
        self.assertFalse(parse_tasks('"NotProtonVPN.exe","123","Console","1","1,024 K"\n'))
        self.assertTrue(parse_tasks('"ProtonVPN.exe","123","Console","1","1,024 K"\n'))
        self.assertTrue(parse_tasks('"ProtonVPN.Client.exe","123","Console","1","1,024 K"\n'))
        self.assertTrue(parse_tasks('"ProtonVPN.Launcher.exe","123","Console","1","1,024 K"\n'))

    def test_status_makes_no_unverified_connected_claim(self):
        self.assertEqual(ProtonStatus(True, True, running=True).label, 'App open · tunnel unverified')
        self.assertIn('not prove', ProtonStatus(True, True, adapter_up=True).explanation)

    def test_linux_does_not_probe_windows_tools(self):
        with mock.patch('xvpn.proton.platform.system', return_value='Linux'), \
             mock.patch('xvpn.proton.find_proton_app') as find:
            status = read_proton_status()
            self.assertFalse(status.supported)
            find.assert_not_called()

    def test_windows_process_monitoring_is_read_only(self):
        with mock.patch('xvpn.proton.platform.system', return_value='Windows'), \
             mock.patch('xvpn.proton.find_proton_app', return_value=Path('C:/Proton/ProtonVPN.exe')), \
             mock.patch('xvpn.proton._run_readonly', side_effect=[
                 '"ProtonVPN.Client.exe","2","Console","1","1 K"',
                 '[{"Name":"ProtonVPN", "InterfaceDescription":"ProtonVPN Adapter", "Status":"Up"}]'
             ]) as runner:
            state = read_proton_status()
            self.assertTrue(state.running)
            self.assertTrue(state.adapter_up)
            self.assertEqual(runner.call_count, 2)
            self.assertTrue(all('connect' not in ' '.join(call.args[0]).lower() for call in runner.call_args_list))
            self.assertEqual(runner.call_args_list[0].args[0], ['tasklist.exe', '/FO', 'CSV', '/NH'])

    def test_launch_only_uses_verified_file_and_does_not_connect(self):
        with mock.patch('pathlib.Path.is_file', return_value=True), \
             mock.patch('xvpn.proton.subprocess.Popen') as popen:
            result = launch_proton_app(ProtonStatus(True, True, 'C:/Proton/ProtonVPN.exe'))
            self.assertIn('Opened official', result)
            self.assertEqual(popen.call_args.args[0], ['C:/Proton/ProtonVPN.exe'])
        with self.assertRaises(FileNotFoundError):
            launch_proton_app(ProtonStatus(True, True, 'C:/anything/unknown.exe'))

    def test_proton_5_x_launcher_and_versioned_client(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / 'Proton' / 'VPN'
            version = base / 'v5.1.7'
            version.mkdir(parents=True)
            launcher = base / 'ProtonVPN.Launcher.exe'
            launcher.write_bytes(b'not executed')
            client = version / 'ProtonVPN.Client.exe'
            client.write_bytes(b'not executed')
            with mock.patch('xvpn.proton._candidate_paths', return_value=[launcher, client]), \
                 mock.patch('xvpn.proton._registry_executables', return_value=[]):
                self.assertEqual(find_proton_app(), launcher)
                launcher.unlink()
                self.assertEqual(find_proton_app(), client)
            self.assertIn(client, _folder_executables(base))

    def test_custom_path_and_safe_executable_validation(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            real = Path(temp) / 'ProtonVPN.Launcher.exe'
            real.write_bytes(b'not executed')
            other = Path(temp) / 'ProtonVPN_v5.1.7_x64.exe'
            other.write_bytes(b'not executed')
            with mock.patch('xvpn.proton._candidate_paths', return_value=[]), \
                 mock.patch('xvpn.proton._registry_executables', return_value=[]):
                self.assertEqual(find_proton_app(str(real)), real)
                self.assertIsNone(find_proton_app(str(other)))

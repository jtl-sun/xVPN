"""Offline tests: never actually connect a VPN tunnel or expose test keys."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
from subprocess import CompletedProcess
from xvpn.config_tools import wireguard_settings, make_mtu_test_copy
from xvpn.config_parser import parse_config
from xvpn.backend import VPNBackend
from xvpn.models import VPNProfile

EXAMPLE = '''[Interface]
PrivateKey = TEST_PRIVATE_KEY_SHOULD_NOT_APPEAR_IN_REPORT
Address = 10.2.0.2/32
DNS = 10.2.0.1

[Peer]
PublicKey = TEST_PEER_KEY_SHOULD_NOT_APPEAR_IN_REPORT
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = 192.0.2.2:51820
'''

class MTUDiagnosticsTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'xVPN_USA-US-FREE-140.conf'
        self.source.write_text(EXAMPLE, encoding='utf-8')
        self.out = Path(self.temp.name) / 'variants'

    def test_settings_never_disclose_keys(self):
        settings = wireguard_settings(self.source)
        self.assertEqual(settings['mtu'], 'Automatic (not set)')
        self.assertIn('192.0.2.2:51820', settings['endpoint'])
        self.assertEqual(settings['routes'], '0.0.0.0/0, ::/0')
        self.assertNotIn('TEST_PRIVATE_KEY', repr(settings))
        self.assertNotIn('TEST_PEER_KEY', repr(settings))

    def test_created_config_preserves_original_and_is_valid(self):
        original = self.source.read_bytes()
        target = make_mtu_test_copy(self.source, self.out, 1360)
        self.assertNotEqual(target, self.source)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(wireguard_settings(target)['mtu'], '1360')
        self.assertEqual(parse_config(target).host, '192.0.2.2')
        self.assertIn('TEST_PRIVATE_KEY', target.read_text())

    def test_existing_mtu_replaced_only_in_interface(self):
        self.source.write_text(EXAMPLE.replace('Address = 10.2.0.2/32', 'MTU = 1420\nAddress = 10.2.0.2/32'), encoding='utf-8')
        target = make_mtu_test_copy(self.source, self.out, 1280)
        self.assertEqual(target.read_text().count('MTU ='), 1)
        self.assertEqual(wireguard_settings(target)['mtu'], '1280')

    def test_uniqueness_and_mtu_validation(self):
        a = make_mtu_test_copy(self.source, self.out, 1360)
        b = make_mtu_test_copy(self.source, self.out, 1360)
        self.assertNotEqual(a, b)
        with self.assertRaises(ValueError):
            make_mtu_test_copy(self.source, self.out, 700)

    def test_transfer_counters_no_peer_keys(self):
        backend = VPNBackend()
        backend.system = 'Windows'
        profile = VPNProfile.create(config_path=str(self.source), name='US', provider='Proton VPN',
                                    country='United States', protocol='WireGuard')
        with mock.patch.object(backend, '_wg_status_executable', return_value='wg.exe'), \
             mock.patch('xvpn.backend._run', return_value=CompletedProcess([], 0,
                 'peer_private_key_example 100 200\npeer_second 300 400\n', '')):
            self.assertEqual(backend.wireguard_transfer(profile), (400, 600))
        with mock.patch.object(backend, '_wg_status_executable', return_value='wg.exe'), \
             mock.patch('xvpn.backend._run', return_value=CompletedProcess([], 1, '', 'error')):
            self.assertIsNone(backend.wireguard_transfer(profile))

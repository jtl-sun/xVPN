"""Offline tests: WireGuard client is never invoked for a live VPN connection."""
from pathlib import Path
from unittest import TestCase, mock
from tempfile import TemporaryDirectory
from xvpn.backend import (VPNBackend, VPNError, WireGuardHandshake,
                          parse_latest_handshakes, ConnectionAttempt)
from xvpn.models import VPNProfile


class HandshakeTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / 'xVPN_USA.conf'
        path.write_text('[Interface]\nPrivateKey=example\nDNS=10.2.0.1\n[Peer]\nEndpoint=example.com:51820\n')
        self.profile = VPNProfile.create(config_path=str(path), name='USA',
                                         provider='Proton VPN', country='US', protocol='WireGuard')
        self.backend = VPNBackend()
        self.backend.system = 'Windows'

    def test_parse_missing_recent_and_stale_without_keys(self):
        self.assertEqual(parse_latest_handshakes('some-peer 0', now=100).state, 'missing')
        result = parse_latest_handshakes('public-key-1 960\npublic-key-2 0\n', now=1000)
        self.assertEqual((result.state, result.age_seconds), ('verified', 40))
        self.assertEqual(parse_latest_handshakes('public-key 100', now=1000).state, 'stale')
        self.assertEqual(parse_latest_handshakes('', now=1000).state, 'missing')

    def test_verified_connection_is_not_disconnected(self):
        with mock.patch.object(self.backend, 'active', return_value=False), \
             mock.patch.object(self.backend, '_wg_status_executable', return_value='wg.exe'), \
             mock.patch.object(self.backend, 'connect', return_value='Tunnel activated'), \
             mock.patch.object(self.backend, '_wait_for_handshake', return_value=WireGuardHandshake('verified', 3)), \
             mock.patch.object(self.backend, 'disconnect') as disconnect:
            result = self.backend.connect_verified(self.profile)
            self.assertTrue(result.handshake_verified)
            disconnect.assert_not_called()

    def test_missing_handshake_recovers_only_newly_started_tunnel(self):
        with mock.patch.object(self.backend, 'active', return_value=False), \
             mock.patch.object(self.backend, '_wg_status_executable', return_value='wg.exe'), \
             mock.patch.object(self.backend, 'connect', return_value='Tunnel activated'), \
             mock.patch.object(self.backend, '_wait_for_handshake', return_value=WireGuardHandshake('missing')), \
             mock.patch.object(self.backend, 'disconnect', return_value='Disconnected') as disconnect:
            result = self.backend.connect_verified(self.profile)
            self.assertTrue(result.recovered)
            self.assertFalse(result.handshake_verified)
            self.assertIn('restore normal Internet', result.message)
            disconnect.assert_called_once_with(self.profile)

    def test_preexisting_tunnel_is_never_rolled_back(self):
        with mock.patch.object(self.backend, 'active', return_value=True), \
             mock.patch.object(self.backend, 'connect') as connect, \
             mock.patch.object(self.backend, 'disconnect') as disconnect:
            result = self.backend.connect_verified(self.profile)
            self.assertFalse(result.recovered)
            connect.assert_not_called()
            disconnect.assert_not_called()

    def test_racing_preexisting_tunnel_is_not_rolled_back(self):
        with mock.patch.object(self.backend, 'active', return_value=False), \
             mock.patch.object(self.backend, '_wg_status_executable', return_value='wg.exe'), \
             mock.patch.object(self.backend, 'connect', return_value='Tunnel/process already active; public IP verification recommended.'), \
             mock.patch.object(self.backend, 'disconnect') as disconnect:
            result = self.backend.connect_verified(self.profile)
            self.assertIn('preexisting', result.message)
            disconnect.assert_not_called()

    def test_failure_to_recover_is_visible_not_success(self):
        with mock.patch.object(self.backend, 'active', return_value=False), \
             mock.patch.object(self.backend, '_wg_status_executable', return_value='wg.exe'), \
             mock.patch.object(self.backend, 'connect', return_value='Tunnel activated'), \
             mock.patch.object(self.backend, '_wait_for_handshake', return_value=WireGuardHandshake('unavailable')), \
             mock.patch.object(self.backend, 'disconnect', side_effect=VPNError('access denied')):
            result = self.backend.connect_verified(self.profile)
            self.assertTrue(result.recovery_failed)
            self.assertIn('Activate', result.message.replace('Deactivate', 'Activate'))

    def test_no_status_tool_refuses_new_connection(self):
        with mock.patch.object(self.backend, 'active', return_value=False), \
             mock.patch.object(self.backend, '_wg_status_executable', return_value=None), \
             mock.patch.object(self.backend, 'connect') as connect:
            with self.assertRaisesRegex(VPNError, 'wg.exe'):
                self.backend.connect_verified(self.profile)
            connect.assert_not_called()

    def test_status_does_not_show_public_key(self):
        from subprocess import CompletedProcess
        with mock.patch.object(self.backend, '_wg_status_executable', return_value='wg.exe'), \
             mock.patch('xvpn.backend._run', return_value=CompletedProcess([], 0, 'sensitive-peer-key 1770000000\n', '')):
            result = self.backend.wireguard_handshake(self.profile)
            self.assertNotIn('sensitive-peer', result.detail)

    def test_internal_probe_only_targets_rfc1918(self):
        with mock.patch('xvpn.backend.socket.socket') as sock:
            self.backend._probe_wireguard_internal_dns(self.profile)
            sock.return_value.__enter__.return_value.sendto.assert_called_once_with(b'', ('10.2.0.1', 53))
        Path(self.profile.config_path).write_text('[Interface]\nDNS=8.8.8.8\n[Peer]\nEndpoint=example.com:51820\n')
        with mock.patch('xvpn.backend.socket.socket') as sock:
            self.backend._probe_wireguard_internal_dns(self.profile)
            sock.assert_not_called()

    def test_proton_download_is_official_url(self):
        from xvpn.proton import PROTON_DOWNLOAD_URL
        self.assertEqual(PROTON_DOWNLOAD_URL, 'https://protonvpn.com/download-windows')

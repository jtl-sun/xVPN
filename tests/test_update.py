import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xvpn.backend import VPNBackend, VPNError, _run
from xvpn.config_parser import parse_config, ConfigError
from xvpn.models import VPNProfile

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'test.conf'
        self.path.write_text('[Interface]\nPrivateKey=secret\n[Peer]\nEndpoint=example.com:51820\n')
        self.profile = VPNProfile.create(config_path=str(self.path), name='Test', provider='Test', country='JP', protocol='WireGuard')

    def test_rejects_hooks_even_after_endpoint(self):
        with self.path.open('a') as f:
            f.write('[Interface]\nPostUp = arbitrary-command\n')
        with self.assertRaises(ConfigError):
            parse_config(self.path)

    def test_rejects_nested_openvpn_and_option_alias(self):
        path = self.path.with_suffix('.ovpn')
        for directive in ['config other.conf', '--up evil', 'tls-verify evil', 'iproute evil']:
            path.write_text('remote example.com 443\n' + directive)
            with self.assertRaises(ConfigError):
                parse_config(path)

    def test_udp_does_not_report_dns_timing(self):
        with patch('xvpn.backend.socket.create_connection') as connection:
            with self.assertRaises(VPNError):
                VPNBackend().latency(self.profile)
            connection.assert_not_called()

    def test_existing_tunnel_is_not_reinstalled(self):
        backend = VPNBackend()
        backend.system = 'Windows'
        with patch.object(backend, '_wireguard_executable', return_value='wireguard.exe'), patch('xvpn.backend._run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            with self.assertRaises(VPNError):
                backend._connect_wireguard(self.profile)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][0], 'sc.exe')

    def test_permission_error_does_not_install(self):
        backend = VPNBackend()
        backend.system = 'Windows'
        with patch.object(backend, '_wireguard_executable', return_value='wireguard.exe'), patch('xvpn.backend._run', return_value=subprocess.CompletedProcess([], 5, '', 'Access denied')) as run:
            with self.assertRaises(VPNError):
                backend._connect_wireguard(self.profile)
            self.assertEqual(run.call_count, 1)

    def test_console_hidden_on_windows(self):
        with patch('xvpn.backend.os.name', 'nt'), patch.object(subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True), patch('xvpn.backend.subprocess.run') as run:
            _run(['sc.exe', 'query'])
            self.assertEqual(run.call_args.kwargs['creationflags'], 0x08000000)

    def test_connect_rechecks_changed_file(self):
        self.path.write_text('[Interface]\nPostUp=evil\n[Peer]\nEndpoint=example.com:51820')
        with patch.object(VPNBackend, '_connect_wireguard') as connect:
            with self.assertRaises(ConfigError):
                VPNBackend().connect(self.profile)
            connect.assert_not_called()

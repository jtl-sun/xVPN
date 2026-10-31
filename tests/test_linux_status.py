import subprocess
from unittest.mock import patch
import unittest
from xvpn.backend import VPNBackend
from xvpn.models import VPNProfile

class LinuxTunnelDetectionTests(unittest.TestCase):
    def setUp(self):
        self.profile = VPNProfile.create(config_path='/tmp/my-vpn.conf', name='test', provider='private', country='Japan', protocol='WireGuard')

    def test_wireguard_interface_is_detected_without_nm(self):
        b = VPNBackend()
        b.system = 'Linux'
        with patch('xvpn.backend.shutil.which', side_effect=lambda cmd: '/usr/bin/wg' if cmd=='wg' else None), \
             patch('xvpn.backend._run', return_value=subprocess.CompletedProcess([], 0, 'wg0 my-vpn wg2\n', '')) as run:
            self.assertTrue(b.active(self.profile))
            run.assert_called_once()

    def test_unknown_interface_is_inactive(self):
        b = VPNBackend()
        b.system = 'Linux'
        with patch('xvpn.backend.shutil.which', side_effect=lambda cmd: '/usr/bin/wg' if cmd=='wg' else None), \
             patch('xvpn.backend._run', return_value=subprocess.CompletedProcess([], 0, 'wg0\n', '')):
            self.assertFalse(b.active(self.profile))

if __name__ == '__main__':
    unittest.main()

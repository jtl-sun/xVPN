from pathlib import Path
import tempfile
import unittest
from xvpn.models import VPNProfile
from xvpn.prefs import Preferences
from xvpn.ui_logic import visible_profiles, sort_profiles, count_active


class UIStateTests(unittest.TestCase):
    def setUp(self):
        self.us = VPNProfile.create(config_path=__file__, name='United States 1', provider='ProviderA', country='United States', protocol='WireGuard', endpoint_host='us.example')
        self.jp = VPNProfile.create(config_path=__file__, name='Japan 2', provider='ProviderB', country='Japan', protocol='OpenVPN', endpoint_host='jp.example')
        self.kr = VPNProfile.create(config_path=__file__, name='South Korea 3', provider='ProviderA', country='South Korea', protocol='OpenVPN', endpoint_host='kr.example')
        self.rows = [self.us, self.jp, self.kr]
        self.states = {self.us.id: 'Active*', self.jp.id: 'Inactive', self.kr.id: 'Unknown'}

    def test_country_and_provider_filters(self):
        self.assertEqual(visible_profiles(self.rows, self.states, 'country:Japan'), [self.jp])
        self.assertEqual(visible_profiles(self.rows, self.states, 'provider:ProviderA'), [self.us, self.kr])

    def test_active_filters_and_search(self):
        self.assertEqual(visible_profiles(self.rows, self.states, 'active'), [self.us])
        self.assertEqual(visible_profiles(self.rows, self.states, 'inactive'), [self.jp])
        self.assertEqual(visible_profiles(self.rows, self.states, search='JP.EXAMPLE'), [self.jp])
        self.assertEqual(count_active(self.states, self.rows), 1)

    def test_sort_by_country_and_name(self):
        self.assertEqual(sort_profiles(self.rows, self.states, 'country')[0], self.jp)
        self.assertEqual(sort_profiles(self.rows, self.states, 'name', True)[0], self.us)

    def test_preferences_are_separate_from_profiles(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Preferences(Path(temp) / 'prefs.json')
            self.assertEqual(store.load()['theme'], 'light')
            store.save('dark')
            self.assertEqual(store.load()['theme'], 'dark')
            with self.assertRaises(ValueError):
                store.save('neon')


if __name__ == '__main__':
    unittest.main()

class ProtonPathPreferenceTests(unittest.TestCase):
    def test_manual_proton_path_survives_theme_changes(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            store = Preferences(Path(temp) / 'prefs.json')
            store.set_proton_path(r'C:\Program Files\Proton\VPN\ProtonVPN.Launcher.exe')
            store.save('dark')
            self.assertEqual(store.load()['theme'], 'dark')
            self.assertEqual(store.load()['proton_path'], r'C:\Program Files\Proton\VPN\ProtonVPN.Launcher.exe')

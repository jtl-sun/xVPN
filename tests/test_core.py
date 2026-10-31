from pathlib import Path
import tempfile
import unittest

from xvpn.config_parser import ConfigError, parse_config
from xvpn.models import VPNProfile
from xvpn.store import ProfileStore


class ConfigParserTests(unittest.TestCase):
    def write(self, suffix: str, text: str) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8")
        handle.write(text)
        handle.close()
        self.addCleanup(Path(handle.name).unlink, missing_ok=True)
        return Path(handle.name)

    def test_openvpn_endpoint(self) -> None:
        path = self.write(".ovpn", "client\nremote vpn.example.com 443 tcp\nauth-user-pass\n")
        parsed = parse_config(path)
        self.assertEqual((parsed.protocol, parsed.host, parsed.port), ("OpenVPN", "vpn.example.com", 443))
        self.assertTrue(parsed.needs_credentials)

    def test_rejects_script_execution(self) -> None:
        path = self.write(".ovpn", "remote x.example 1194\nup evil.sh\n")
        with self.assertRaises(ConfigError):
            parse_config(path)

    def test_wireguard_endpoint(self) -> None:
        path = self.write(".conf", "[Interface]\nPrivateKey = secret\n[Peer]\nEndpoint = wg.example.com:51820\n")
        parsed = parse_config(path)
        self.assertEqual((parsed.protocol, parsed.host, parsed.port), ("WireGuard", "wg.example.com", 51820))


class StoreTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory) / "profiles.json")
            profile = VPNProfile.create(
                config_path=__file__, name="Test", provider="Provider", country="JP",
                protocol="OpenVPN", endpoint_host="example.com", endpoint_port=443,
            )
            store.save([profile])
            loaded = store.load()
            self.assertEqual(loaded[0].name, "Test")
            self.assertEqual(loaded[0].endpoint_port, 443)


if __name__ == "__main__":
    unittest.main()

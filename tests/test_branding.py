"""Asset smoke tests without adding any third-party runtime dependency."""
from pathlib import Path
import struct
import unittest

from xvpn.branding import ASSET_DIR, ICON_PATH, COMPACT_PNG_PATH

class BrandingTests(unittest.TestCase):
    def test_windows_icon_contains_small_and_large_frames(self):
        data=ICON_PATH.read_bytes()
        reserved,kind,count=struct.unpack_from('<HHH',data)
        self.assertEqual((reserved,kind),(0,1))
        sizes=set()
        for idx in range(count):
            width,height,colors,unused,planes,bpp,length,offset=struct.unpack_from('<BBBBHHII',data,6+idx*16)
            size=width or 256
            self.assertEqual(size,height or 256)
            self.assertEqual(data[offset:offset+8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(bpp,32)
            sizes.add(size)
        self.assertTrue({16,24,32,48,64,128,256}.issubset(sizes))

    def test_bundled_png_and_shortcut(self):
        self.assertEqual(COMPACT_PNG_PATH.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
        self.assertTrue((ASSET_DIR/'xvpn.png').exists())
        root=Path(__file__).parents[1]
        windows_script=(root/'install_windows.bat').read_text()
        ubuntu_script=(root/'install_ubuntu.sh').read_text()
        self.assertIn('xvpn\\assets\\xvpn.ico,0',windows_script)
        self.assertIn('Icon=$app_dir/xvpn/assets/xvpn_compact.png',ubuntu_script)
        self.assertIn('xcopy /E /I /Y',windows_script)

    def test_version_and_gui_icon_integration(self):
        root=Path(__file__).parents[1]
        source=(root/'xvpn/gui.py').read_text()
        self.assertIn('VERSION = "1.3.5"',source)
        self.assertIn('apply_application_icon(self)',source)
        self.assertIn('self.brand_icon',source)
        self.assertIn('load_header_icon(self)',source)

if __name__ == '__main__':
    unittest.main()

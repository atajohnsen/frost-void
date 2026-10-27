"""Run with: python3 -m unittest discover -s tests -v"""
import colorsys
import importlib.util
import json
import os
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'share/frost'))
import core
import theme


class ThemeTests(unittest.TestCase):
    def test_accents_are_legible_across_hues_and_modes(self):
        for hue in range(0,360,5):
            for saturation in (0,.1,.5,1):
                seed=theme.hex_color(colorsys.hls_to_rgb(hue/360,.5,saturation))
                for mode in ('dark','light'):
                    p=theme.palette(seed,mode)
                    for key in ('accent','secondary','tertiary'):
                        self.assertGreaterEqual(theme.contrast(p[key],p['surface']),4.5)
                    self.assertGreaterEqual(theme.contrast(p['foreground'],p['surface']),7)
                    self.assertGreaterEqual(theme.contrast(p['muted'],p['surface']),4.5)

    def test_generated_colors_retain_accent_hue(self):
        for hue in range(0,360,15):
            seed=theme.hex_color(colorsys.hls_to_rgb(hue/360,.5,.8))
            for mode in ('dark','light'):
                p=theme.palette(seed,mode)
                for key in ('accent','secondary','tertiary'):
                    h,_,s=colorsys.rgb_to_hls(*theme.rgb(p[key]))
                    error=abs(h-hue/360)
                    self.assertLess(min(error,1-error),.025)

    def test_grayscale_images_stay_grayscale(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'Gray wallpaper.png'
            Image.new('RGB',(40,40),(140,140,140)).save(path)
            with patch.object(theme,'CACHE',Path(temp)/'cache'):
                seed=theme.extract(path)
            self.assertLess(colorsys.rgb_to_hls(*theme.rgb(seed))[2],.01)

    def test_populous_wallpaper_color_beats_tiny_bright_detail(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'water; "test" $.png'
            image=Image.new('RGB',(100,100),(25,100,180))
            image.putpixel((0,0),(255,0,0))
            image.save(path)
            with patch.object(theme,'CACHE',Path(temp)/'cache'):
                seed=theme.extract(path)
            self.assertLess(abs(colorsys.rgb_to_hls(*theme.rgb(seed))[0]-.586),.04)

    def test_modified_image_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'image.png'
            with patch.object(theme,'CACHE',Path(temp)/'cache'):
                Image.new('RGB',(30,30),'red').save(path)
                first=theme.extract(path)
                Image.new('RGB',(30,30),'blue').save(path)
                os.utime(path,ns=(1234567890000000000,1234567890000000000))
                second=theme.extract(path)
            self.assertNotEqual(first,second)

    def test_render_all_outputs_without_session_or_wallpaper(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.multiple(theme,CONFIG=root/'config',DATA=root/'data',GENERATED=root/'generated'):
                for mode in ('dark','light'):
                    theme.render(theme.palette('#ffe000',mode),'/tmp/has spaces; dollar$.png')
                    self.assertIn('fill',(root/'generated/wallpaper.conf').read_text())
                    self.assertEqual(json.loads((root/'generated/palette.json').read_text())['mode'],mode)
                    self.assertTrue((root/'generated/kitty.conf').exists())
                    self.assertTrue((root/'config/gtk-4.0/gtk.css').exists())
                    self.assertTrue((root/'config/qt6ct/qt6ct.conf').exists())

    def test_preview_leaves_saved_selection_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            image=root/'image.png'
            Image.new('RGB',(20,20),'purple').save(image)
            saved={'mode':'dark','wallpaper':None}
            with patch.multiple(theme,CONFIG=root/'config',DATA=root/'data',GENERATED=root/'generated',
                                STATE=root/'state',CACHE=root/'cache'), patch.object(theme,'state',return_value=saved):
                theme.apply(str(image),'light',persist=False,reload=False)
                self.assertFalse((root/'state/state.json').exists())
                theme.apply(str(image),'light',persist=True,reload=False)
                self.assertEqual(json.loads((root/'state/state.json').read_text())['wallpaper'],str(image))


class IPCTests(unittest.TestCase):
    def test_receive_handles_fragmented_messages(self):
        payload=b'{"ok":true}'
        data=b'i3-ipc'+struct.pack('=II',len(payload),4)+payload
        class Stream:
            def recv(self,n):
                nonlocal data
                answer,data=data[:min(n,3)],data[min(n,3):]
                return answer
        kind,value=core.receive(Stream())
        self.assertEqual((kind,value),(4,{'ok':True}))

    def test_disconnect_is_detected(self):
        class Stream:
            def recv(self,n):return b''
        with self.assertRaises(ConnectionError):
            core.receive(Stream())

    def test_sway_arguments_are_quoted(self):
        value='/path/with spaces; dollar$ and "quotes".png'
        result=core.quote(value)
        self.assertTrue(result.startswith('"') and result.endswith('"'))
        self.assertIn('\\"',result)
        self.assertIn('\\$',result)
        with self.assertRaises(ValueError):
            core.quote('line\nbreak')

    def test_atomic_file_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'nested/state.json'
            core.write_json(path,{'message':'Bokmål, blåbær'})
            core.write_json(path,{'message':'new'})
            self.assertEqual(core.read_json(path),{'message':'new'})
            self.assertEqual(list(path.parent.glob('.frost-*')),[])


if __name__=='__main__':
    unittest.main()

"""B5: lib/card.js, which image the card shows and where it goes (node)."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import jsnode  # noqa: E402


def call(expr):
    return jsnode.call(expr, Card="card")


@unittest.skipUnless(jsnode.NODE, "node not installed")
class CardLib(unittest.TestCase):
    def test_only_a_stored_picture_makes_a_card(self):
        note = ('{objects:[{kind:"letter",body:"hi"},'
                '{kind:"image",attrs:{url:"u"},body:"cap",image:'
                '{status:"%s",local:"%s",source:"https://h/a.png",host:"h",'
                'w:10,h:5}}]}')
        self.assertIsNone(call(f"Card.imageOf({note % ('loading', '')})"))
        self.assertIsNone(call(f"Card.imageOf({note % ('refused', '')})"))
        self.assertIsNone(call(f"Card.imageOf({note % ('ready', '')})"))
        got = call(f"Card.imageOf({note % ('ready', '/d/a.png')})")
        self.assertEqual((got["local"], got["source"], got["caption"]),
                         ("/d/a.png", "https://h/a.png", "cap"))
        for none in ("null", "undefined", "{}", "{objects:5}"):
            self.assertIsNone(call(f"Card.imageOf({none})"))

    def test_the_source_line_is_visible_and_bounded(self):
        short = call('Card.sourceLine("https://h.org/a.png")')
        self.assertEqual(short, "h.org/a.png")
        long_ = call('Card.sourceLine("https://upload.wikimedia.org/'
                     'wikipedia/commons/a/ab/' + "x" * 80 + '.png")')
        self.assertLessEqual(len(long_), 44)
        self.assertIn("...", long_)

    def test_file_url_escapes_the_path(self):
        self.assertEqual(call('Card.fileUrl("/a b/c#d.png")'),
                         "file:///a%20b/c%23d.png")

    def test_size_keeps_the_aspect_and_never_grows_a_small_picture(self):
        wide = call("Card.cardSize({w:1000,h:500})")
        self.assertEqual((wide["picW"], wide["picH"]), (280, 140))
        tall = call("Card.cardSize({w:200,h:600})")
        self.assertEqual((tall["picW"], tall["picH"]), (67, 200))
        tiny = call("Card.cardSize({w:40,h:30})")
        self.assertEqual((tiny["picW"], tiny["picH"]), (40, 30))
        unknown = call("Card.cardSize(null)")
        self.assertEqual((unknown["picW"], unknown["picH"]), (280, 200))

    def place(self, avoid, w=1280, h=720, size="{w:296,h:184}"):
        return call(f"Card.place({w},{h},{size},{avoid})")

    def test_a_point_on_the_left_puts_the_card_on_the_right(self):
        avoid = "Card.avoidRects([{x:200,y:300,label:'a',index:1}],[],null,null)"
        got = self.place(avoid)
        self.assertTrue(got["clear"])
        self.assertGreater(got["x"], 1280 / 2)

    def test_a_point_on_the_right_puts_it_on_the_left(self):
        avoid = "Card.avoidRects([{x:1100,y:300}],[],null,null)"
        got = self.place(avoid)
        self.assertTrue(got["clear"])
        self.assertLess(got["x"], 1280 / 2)

    def test_it_never_overlaps_any_avoided_rectangle_when_there_is_room(self):
        avoid = ("Card.avoidRects([{x:200,y:300}],"
                 "[{kind:'ring',x:1000,y:150,r:60},"
                 "{kind:'hl',x:500,y:500,w:200,h:100},"
                 "{kind:'arrow',x1:100,y1:100,x2:300,y2:200}],"
                 "{x:640,y:360},{x:400,y:50,w:480,h:90})")
        got = call(f"(function(){{var av={avoid};"
                   "var s={w:296,h:184};var p=Card.place(1280,720,s,av);"
                   "var box={x:p.x,y:p.y,w:s.w,h:s.h};var hit=0;"
                   "for(var i=0;i<av.length;i++)hit+=Card.overlap(box,av[i]);"
                   "return [p,hit]})()")
        self.assertEqual(got[1], 0)
        self.assertTrue(got[0]["clear"])

    def test_the_card_stays_inside_the_layer(self):
        for w, h in ((1280, 720), (400, 300), (320, 240)):
            p = self.place("[]", w, h)
            self.assertGreaterEqual(p["x"], 0)
            self.assertGreaterEqual(p["y"], 0)
            self.assertLessEqual(p["x"] + 296, max(w, 296))
            self.assertLessEqual(p["y"] + 184, max(h, 184))

    def test_when_nothing_is_free_the_least_overlapping_spot_wins(self):
        everything = "[{x:0,y:0,w:1280,h:720}]"
        p = self.place(everything)
        self.assertFalse(p["clear"])

    def test_an_unknown_avoid_entry_changes_nothing(self):
        self.assertEqual(call("Card.avoidRects(null,undefined,5,null)"), [])


if __name__ == "__main__":
    unittest.main()

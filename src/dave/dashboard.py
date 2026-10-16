"""`dave dashboard`: a local page to ask Dave for a trip, wait while he plans it, and browse it.

It runs on Python's own `http.server`, bound to 127.0.0.1, so there is nothing extra to
install or host and it works the same on Windows and Mac/Linux. The form calls the same
planner as `dave plan`. The reply is T33's Markdown itinerary, shown as one card per day,
the cost table, the validator's "Not final" warnings and the bookings waiting for approval.
There are no payment or booking buttons: approving and booking stay outside (CLAUDE.md rule 1).
"""

import asyncio
import html
import re
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import markdown

DEMO_DIR = Path(__file__).resolve().parents[2] / "demo"
RV_ICON = (Path(__file__).parent / "rv_icon.svg").read_text()
FIELDS = ("rv", "origin", "destination", "start_date", "nights", "budget", "interests", "notes")

Planner = Callable[[str], str]  # trip request in, Markdown itinerary out


def agent_planner(request: str) -> str:
    """The planner behind `dave plan`."""
    from dave.agent import plan

    return asyncio.run(plan(request))


def demo_requests(demo_dir: Path = DEMO_DIR) -> list[str]:
    """The numbered trip requests in demo/README.md."""
    text = (demo_dir / "README.md").read_text()
    return re.findall(r'^\d+\. "(.+)"$', text, flags=re.MULTILINE)


def saved_itineraries(demo_dir: Path = DEMO_DIR) -> list[Path]:
    """Itineraries already rendered into demo/ (T33, T35)."""
    return sorted(demo_dir.glob("itinerary-*.md"))


def trip_request(form: dict[str, str]) -> str:
    """One plain-language request from the form, the way a user would type it to `dave plan`."""
    if text := form.get("request", "").strip():
        return text  # a demo trip, sent as written
    f = {k: form.get(k, "").strip() for k in FIELDS}
    parts = []
    if f["rv"]:
        parts.append(f"We have a {f['rv']}.")
    if f["origin"] or f["destination"]:
        parts.append(f"{f['origin'] or 'Home'} to {f['destination'] or 'somewhere fun'}.")
    if f["nights"]:
        parts.append(
            f"{f['nights']} nights" + (f" from {f['start_date']}." if f["start_date"] else ".")
        )
    elif f["start_date"]:
        parts.append(f"Leaving {f['start_date']}.")
    if f["budget"]:
        parts.append(f"Budget ${f['budget'].lstrip('$')}.")
    if f["interests"]:
        parts.append(f"We love {f['interests']}.")
    if f["notes"]:
        parts.append(f["notes"])
    return " ".join(parts)


def itinerary_html(text: str) -> str:
    """T33's Markdown as HTML: the header, then a card per day, costs and bookings."""
    text = text.replace("<", "&lt;")
    # T33 puts lists right under a bold line ("**Tonight**"); Python-Markdown needs a blank line.
    text = re.sub(r"^(?!- )(.+)\n(?=- )", r"\1\n\n", text, flags=re.MULTILINE)
    sections = re.split(r"^(?=## )", text, flags=re.MULTILINE)
    out = []
    for i, section in enumerate(sections):
        body = markdown.markdown(section, extensions=["tables"])
        body = body.replace("<a href=", '<a target="_blank" rel="noopener" href=')
        if i == 0:
            out.append(f'<header class="trip">{body}</header>')
            continue
        first_word = (section[3:].split() or [""])[0]
        kind = {"Day": "day", "Costs": "costs", "Bookings": "bookings"}.get(first_word, "other")
        out.append(f'<section class="card {kind}">{body}</section>')
    return "\n".join(out)


def page(body: str, form: dict[str, str] | None = None, demo_dir: Path = DEMO_DIR) -> str:
    """The whole page: RV icon top right, the request form, demo trips, then `body`."""
    form = form or {}

    def field(name: str, label: str, kind: str = "text", hint: str = "") -> str:
        value = html.escape(form.get(name, ""), quote=True)
        return (
            f'<label>{label}<input type="{kind}" name="{name}" value="{value}" '
            f'placeholder="{html.escape(hint, quote=True)}"></label>'
        )

    demos = "".join(
        f'<form method="post" action="/plan"><input type="hidden" name="request" '
        f'value="{html.escape(r, quote=True)}"><button class="demo" type="submit">'
        f"{i}. {html.escape(r)}</button></form>"
        for i, r in enumerate(demo_requests(demo_dir), 1)
    )
    saved = "".join(
        f'<li><a href="/saved/{p.name}">{html.escape(p.stem)}</a></li>'
        for p in saved_itineraries(demo_dir)
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dave RV trips</title><style>{CSS}</style></head>
<body>
<div class="rv-icon">{RV_ICON}</div>
<main>
<h1><a href="/">Dave</a> <small>plans RV trips your rig fits</small></h1>
<form class="request" method="post" action="/plan">
{field("rv", "RV", hint="2023 Winnebago Minnie Winnie 31K")}
{field("origin", "From", hint="Denver, CO")}
{field("destination", "To", hint="Moab, UT")}
{field("start_date", "Leaving", "date")}
{field("nights", "Nights", "number")}
{field("budget", "Budget ($)", "number")}
{field("interests", "Interests", hint="hiking, big views, BBQ")}
{field("notes", "Anything else", hint="family of four, towing a Jeep")}
<button type="submit">Plan my trip</button>
</form>
<details><summary>Demo trips</summary>{demos}
{f"<p>Already planned:</p><ul>{saved}</ul>" if saved else ""}</details>
<p id="planning" hidden>Dave is planning your trip. Routes, campgrounds and prices take a
minute or two.</p>
{body}
</main>
<script>
for (const f of document.querySelectorAll('form[action="/plan"]'))
  f.addEventListener("submit", () => document.getElementById("planning").hidden = false);
</script>
</body></html>
"""


def handler(planner: Planner, demo_dir: Path = DEMO_DIR) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                return self._send(page("", demo_dir=demo_dir))
            name = self.path.removeprefix("/saved/")
            saved = {p.name: p for p in saved_itineraries(demo_dir)}
            if name in saved:
                return self._send(page(itinerary_html(saved[name].read_text()), demo_dir=demo_dir))
            self._send(page("<p>Not found.</p>", demo_dir=demo_dir), status=404)

        def do_POST(self):
            if self.path != "/plan":
                return self._send(page("<p>Not found.</p>", demo_dir=demo_dir), status=404)
            length = int(self.headers.get("Content-Length", 0))
            raw = parse_qs(self.rfile.read(length).decode())
            form = {k: v[0] for k, v in raw.items()}
            request = trip_request(form)
            if not request:
                body = '<p class="error">Tell Dave where you are going first.</p>'
            else:
                try:
                    body = itinerary_html(planner(request))
                except Exception as e:  # shown on the page instead of a blank error
                    body = f'<p class="error">Dave couldn\'t plan this: {html.escape(str(e))}</p>'
                body = f'<p class="asked">You asked: {html.escape(request)}</p>{body}'
            self._send(page(body, form, demo_dir=demo_dir))

        def _send(self, text: str, status: int = 200):
            data = text.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):  # keep the terminal quiet
            pass

    return Handler


def serve(port: int = 8765, *, open_browser: bool = True, planner: Planner = agent_planner):
    server = ThreadingHTTPServer(("127.0.0.1", port), handler(planner))
    url = f"http://localhost:{server.server_port}/"
    print(f"Dave's dashboard is at {url} (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


CSS = """
:root { --bg: #faf7f0; --card: #fff; --ink: #2b3440; --muted: #6b7684; --line: #e3dccd;
  --accent: #e9785a; --warn-bg: #fff3df; --warn: #a15c00; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #1d2329; --card: #262e36; --ink: #e8e4da; --muted: #9aa5b1; --line: #3a4550;
    --accent: #f08c70; --warn-bg: #3a2f1c; --warn: #f2b45c; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 16px 16px 48px; }
.rv-icon { position: fixed; top: 10px; right: 14px; z-index: 1; }
h1 { margin: 8px 0 16px; padding-right: 64px; }
h1 a { color: var(--ink); text-decoration: none; }
h1 small { font-size: 15px; font-weight: 400; color: var(--muted); }
a { color: var(--accent); }
.request { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px;
  background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 14px; }
label { display: flex; flex-direction: column; font-size: 13px; color: var(--muted); gap: 3px; }
input { font: inherit; color: var(--ink); background: var(--bg); border: 1px solid var(--line);
  border-radius: 6px; padding: 6px 8px; }
button { font: inherit; cursor: pointer; border-radius: 6px; border: 1px solid var(--accent);
  background: var(--accent); color: #fff; padding: 7px 12px; align-self: end; }
button.demo { background: none; color: var(--ink); border-color: var(--line); text-align: left;
  width: 100%; margin: 4px 0; }
details { margin: 14px 0; }
summary { cursor: pointer; color: var(--muted); }
#planning, .asked { color: var(--muted); }
.error { color: var(--warn); }
.trip h1 { font-size: 26px; padding: 0; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 4px 16px 10px; margin: 14px 0; overflow-x: auto; }
.card h2 { font-size: 19px; }
.card.day h2 { color: var(--accent); }
blockquote { margin: 12px 0; padding: 8px 14px; background: var(--warn-bg); color: var(--warn);
  border-left: 4px solid var(--warn); border-radius: 6px; }
table { border-collapse: collapse; width: 100%; }
th, td { padding: 5px 8px; border-bottom: 1px solid var(--line); }
"""

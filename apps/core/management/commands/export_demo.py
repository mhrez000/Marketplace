"""Export the public marketplace as a static site (for GitHub Pages).

    python manage.py export_demo --out _site --base /Marketplace

Renders every public page through the Django test client, rewrites
root-absolute URLs to live under the Pages subpath, injects a "static preview"
banner, and copies the built CSS. Interactive features (login, enquiry, portal)
are stubs here — the banner points people at the repo/Codespaces for the real app.
"""
import re
import shutil
from pathlib import Path

from django.core.management.base import BaseCommand
from django.test import Client

BANNER = (
    '<div style="background:#2F4156;color:#C8D9E6;font-size:13px;padding:9px 16px;'
    'text-align:center;font-family:sans-serif;">Static preview of the Lens marketplace '
    '&mdash; buttons that need a server (login, enquiries, payments) are inactive here. '
    '<a href="https://github.com/mhrez000/Marketplace" style="color:#fff;font-weight:700;">'
    'Run the full interactive app from the repo &rarr;</a></div>'
)

# Static hosts reject POSTs with "405 Not Allowed" — intercept every form
# submission (and disable HTMX polling) with a friendly explainer instead.
PREVIEW_SCRIPT = """
<script>
document.addEventListener('submit', function (e) {
  var m = (e.target.getAttribute('method') || 'get').toLowerCase();
  if (m === 'post') {  // GET forms (search) still work on a static host
    e.preventDefault();
    alert('This is a static preview \\u2014 logging in, enquiries and payments need the real app.\\n\\nRun it in one click: github.com/mhrez000/Marketplace \\u2192 Code \\u2192 Create codespace.');
  }
}, true);
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[hx-get],[hx-post]').forEach(function (el) {
    el.removeAttribute('hx-get'); el.removeAttribute('hx-post'); el.removeAttribute('hx-trigger');
  });
});
</script>
"""


class Command(BaseCommand):
    help = "Export public pages as a static site for GitHub Pages."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="_site")
        parser.add_argument("--base", default="", help="URL prefix, e.g. /Marketplace")

    def handle(self, *args, **opts):
        out = Path(opts["out"])
        base = opts["base"].rstrip("/")
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)

        urls = self._urls()
        client = Client()
        written = 0
        for url in urls:
            resp = client.get(url, SERVER_NAME="localhost", follow=False)
            if resp.status_code != 200:
                self.stderr.write(f"skip {url} ({resp.status_code})")
                continue
            html = resp.content.decode("utf-8")
            html = self._rewrite(html, base)
            target = out / (url.strip("/") or ".") / "index.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(html, encoding="utf-8")
            written += 1

        # Static assets (CSS is pre-built & committed; gradients mean no media).
        css_src = Path("static/css/app.css")
        css_dst = out / "static/css/app.css"
        css_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(css_src, css_dst)
        (out / ".nojekyll").write_text("")

        self.stdout.write(self.style.SUCCESS(f"Exported {written} page(s) to {out}/"))

    def _urls(self):
        from apps.marketplace.geo import SERVICES, SUBURBS
        from apps.workspaces.models import Workspace

        urls = ["/", "/search/", "/pricing/", "/how-it-works/", "/for-creatives/",
                "/browse/", "/accounts/login/", "/accounts/signup/"]
        urls += [f"/p/{ws.slug}/" for ws in Workspace.objects.filter(is_published=True)]
        urls += [f"/{svc}/{sub[1]}/" for svc in SERVICES for sub in SUBURBS]
        return urls

    def _rewrite(self, html, base):
        if base:
            # Root-absolute links/assets -> under the Pages subpath ("//" CDN refs untouched).
            html = re.sub(r'(href|src|action)="/(?!/)', rf'\1="{base}/', html)
        # Inject the preview banner right after the opening <body> tag.
        m = re.search(r"<body[^>]*>", html)
        if m:
            html = html[:m.end()] + "\n" + BANNER + html[m.end():]
        # Intercept POST forms + kill HTMX polling (no server behind Pages).
        html = html.replace("</body>", PREVIEW_SCRIPT + "</body>", 1)
        return html

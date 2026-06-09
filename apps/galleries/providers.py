"""Detect where a delivered gallery link points, for a friendly
'Open in Google Drive' button. Display only — we never proxy the files."""
from urllib.parse import urlparse

# (matching domain fragments, display name, emoji)
PROVIDERS = [
    (("drive.google.com", "docs.google.com", "photos.google.com", "photos.app.goo.gl"), "Google Drive", "📁"),
    (("dropbox.com", "db.tt"), "Dropbox", "📦"),
    (("wetransfer.com", "we.tl"), "WeTransfer", "📤"),
    (("pixieset.com",), "Pixieset", "🖼️"),
    (("pic-time.com",), "Pic-Time", "🖼️"),
    (("shootproof.com",), "ShootProof", "🖼️"),
    (("smugmug.com",), "SmugMug", "🖼️"),
    (("onedrive.live.com", "1drv.ms", "sharepoint.com"), "OneDrive", "📁"),
    (("icloud.com",), "iCloud", "☁️"),
    (("frame.io",), "Frame.io", "🎬"),
    (("vimeo.com",), "Vimeo", "🎬"),
    (("youtube.com", "youtu.be"), "YouTube", "🎬"),
]


def detect_provider(url):
    if not url:
        return {"name": "", "icon": ""}
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for domains, name, icon in PROVIDERS:
        if any(host == d or host.endswith("." + d) for d in domains):
            return {"name": name, "icon": icon}
    return {"name": "External link", "icon": "🔗"}

#!/usr/bin/env python3
"""Vibesbot - Native macOS Window Launcher"""
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
os.chdir(SCRIPT_DIR)


def read_version() -> str:
    path = Path(SCRIPT_DIR) / "VERSION"
    if path.exists():
        return path.read_text().strip()
    return "0.0.0"


def loading_html() -> str:
    version = read_version()
    path = Path(SCRIPT_DIR) / "web" / "static" / "loading.html"
    if path.exists():
        return path.read_text(encoding="utf-8").replace("{{VERSION}}", version)
    return f"""<!DOCTYPE html><html><body style="background:#070809;color:#5CF2FF;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh">VIBESBOT v{version}</body></html>"""


def start_server():
    try:
        from src.web_server import run_dashboard
        run_dashboard(port=8080)
    except Exception as e:
        print(f"Server error: {e}")
        import traceback
        traceback.print_exc()


def main():
    import objc
    from Foundation import NSObject, NSURL, NSURLRequest, NSMakeRect, NSTimer
    from AppKit import (
        NSApplication, NSWindow, NSApp,
        NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
        NSBackingStoreBuffered, NSApplicationActivationPolicyRegular,
    )
    from WebKit import WKWebView, WKWebViewConfiguration

    class AppDelegate(NSObject):
        window = objc.ivar()
        webView = objc.ivar()
        timer = objc.ivar()
        attempts = objc.ivar()

        def applicationDidFinishLaunching_(self, notification):
            self.attempts = 0
            self.createWindow()
            self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.5, self, "checkServer:", None, True
            )

        def createWindow(self):
            config = WKWebViewConfiguration.alloc().init()
            self.webView = WKWebView.alloc().initWithFrame_configuration_(
                NSMakeRect(0, 0, 1400, 900), config
            )
            style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                     NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable)
            self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 1400, 900), style, NSBackingStoreBuffered, False
            )
            self.window.setTitle_("VIBESBOT - Loading...")
            self.window.setContentView_(self.webView)
            self.window.center()
            self.window.makeKeyAndOrderFront_(None)
            self.webView.loadHTMLString_baseURL_(loading_html(), None)
            NSApp.activateIgnoringOtherApps_(True)

        def checkServer_(self, timer):
            self.attempts += 1
            try:
                urllib.request.urlopen("http://127.0.0.1:8080", timeout=1)
                # Keep the native splash visible so a fast boot is still seen.
                if self.attempts < 8:
                    return
                timer.invalidate()
                self.window.setTitle_("VIBESBOT")
                url = NSURL.URLWithString_("http://127.0.0.1:8080")
                self.webView.loadRequest_(NSURLRequest.requestWithURL_(url))
            except Exception:
                if self.attempts > 60:
                    timer.invalidate()
                    self.window.setTitle_("VIBESBOT - Error")
                    error_html = """<!DOCTYPE html>
<html><body style="background:#070809;color:#FF5C7A;font-family:Outfit,-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;text-align:center">
<div>
<p style="font-size:22px;font-weight:700;letter-spacing:.18em;margin-bottom:16px;color:#5CF2FF">VIBESBOT</p>
<p style="font-size:14px">Server failed</p>
<p style="color:#666;margin-top:20px;font-size:12px">Check ~/Library/Logs/Vibesbot.log</p>
</div>
</body></html>"""
                    self.webView.loadHTMLString_baseURL_(error_html, None)

        def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
            return True

        def applicationWillTerminate_(self, notification):
            os.system("pkill -f 'uvicorn.*8080' 2>/dev/null")

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()


if __name__ == "__main__":
    os.system("pkill -f 'uvicorn.*8080' 2>/dev/null")
    time.sleep(0.3)
    main()

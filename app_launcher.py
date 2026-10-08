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
    return (
        "<!DOCTYPE html><html><body style=\"background:#0a0a0a;color:#9a9a9a;"
        "font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:flex;align-items:center;"
        f"justify-content:center;height:100vh\">Vibesbot v{version}</body></html>"
    )


def free_port():
    try:
        from src.runtime import free_listen_port
        free_listen_port(8080)
    except Exception:
        os.system("lsof -nP -iTCP:8080 -sTCP:LISTEN -t 2>/dev/null | xargs kill -9 2>/dev/null")


def ensure_ship_files() -> None:
    """Rebuild large files from .ship before importing the web app."""
    try:
        from src.ship_inflate import inflate_ship
        restored = inflate_ship(Path(SCRIPT_DIR))
        if restored:
            print("ship inflate restored:", ", ".join(restored))
    except Exception as e:
        print(f"ship inflate: {e}")


def start_server():
    ensure_ship_files()
    try:
        from src.updater import purge_retired_installs
        purge_retired_installs()
    except Exception:
        pass
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
        NSAppearance, NSApplication, NSWindow, NSApp, NSMenu, NSMenuItem,
        NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
        NSWindowStyleMaskFullSizeContentView, NSWindowTitleHidden,
        NSBackingStoreBuffered, NSApplicationActivationPolicyRegular,
    )
    from WebKit import WKWebView, WKWebViewConfiguration

    NATIVE_JS = """
    (function(){
      document.documentElement.classList.add('vb-native');
      if (document.body) document.body.classList.add('native-app');
      if (window.__vbNative) return;
      window.__vbNative = true;
      document.addEventListener('contextmenu', function(e){ e.preventDefault(); }, true);
      document.addEventListener('keydown', function(e){
        if ((e.metaKey || e.ctrlKey) && (e.key === 'r' || e.key === 'R') && !window.__vbAllowReload) {
          e.preventDefault();
        }
      }, true);
    })();
    """

    class AppDelegate(NSObject):
        window = objc.ivar()
        webView = objc.ivar()
        timer = objc.ivar()
        attempts = objc.ivar()

        def applicationDidFinishLaunching_(self, notification):
            self.attempts = 0
            self.installMenu()
            self.createWindow()
            self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.5, self, "checkServer:", None, True
            )

        def installMenu(self):
            menubar = NSMenu.alloc().init()
            app_item = NSMenuItem.alloc().init()
            menubar.addItem_(app_item)
            app_menu = NSMenu.alloc().initWithTitle_("Vibesbot")
            settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Settings…", "openSettings:", ","
            )
            settings_item.setTarget_(self)
            app_menu.addItem_(settings_item)
            app_menu.addItem_(NSMenuItem.separatorItem())
            hide_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Hide Vibesbot", "hide:", "h"
            )
            app_menu.addItem_(hide_item)
            app_menu.addItem_(NSMenuItem.separatorItem())
            quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Quit Vibesbot", "terminate:", "q"
            )
            quit_item.setTarget_(NSApp)
            app_menu.addItem_(quit_item)
            app_item.setSubmenu_(app_menu)

            view_item = NSMenuItem.alloc().init()
            menubar.addItem_(view_item)
            view_menu = NSMenu.alloc().initWithTitle_("View")
            refresh_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Reload", "refreshPage:", "r"
            )
            refresh_item.setTarget_(self)
            view_menu.addItem_(refresh_item)
            view_item.setSubmenu_(view_menu)
            NSApp.setMainMenu_(menubar)

        def refreshPage_(self, sender):
            if self.webView:
                self.webView.reload()

        def openSettings_(self, sender):
            if not self.webView:
                return
            self.webView.evaluateJavaScript_completionHandler_(
                "window.__vbOpenSettings && window.__vbOpenSettings();",
                None,
            )

        def webView_willOpenMenu_withEvent_(self, webView, menu, event):
            try:
                menu.removeAllItems()
            except Exception:
                pass

        def webView_didFinishNavigation_(self, webView, navigation):
            try:
                webView.evaluateJavaScript_completionHandler_(NATIVE_JS, None)
            except Exception:
                pass

        def createWindow(self):
            config = WKWebViewConfiguration.alloc().init()
            try:
                prefs = config.preferences()
                prefs.setValue_forKey_(False, "developerExtrasEnabled")
            except Exception:
                pass
            self.webView = WKWebView.alloc().initWithFrame_configuration_(
                NSMakeRect(0, 0, 1400, 900), config
            )
            try:
                self.webView.setUIDelegate_(self)
                self.webView.setNavigationDelegate_(self)
                self.webView.setAllowsBackForwardNavigationGestures_(False)
            except Exception:
                pass
            style = (
                NSWindowStyleMaskTitled
                | NSWindowStyleMaskClosable
                | NSWindowStyleMaskMiniaturizable
                | NSWindowStyleMaskResizable
                | NSWindowStyleMaskFullSizeContentView
            )
            self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 1400, 900), style, NSBackingStoreBuffered, False
            )
            self.window.setTitle_("Vibesbot")
            try:
                self.window.setTitlebarAppearsTransparent_(True)
                self.window.setTitleVisibility_(NSWindowTitleHidden)
                self.window.setMovableByWindowBackground_(True)
                dark = NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua")
                self.window.setAppearance_(dark)
                NSApp.setAppearance_(dark)
            except Exception:
                pass
            self.window.setContentView_(self.webView)
            self.window.center()
            self.window.makeKeyAndOrderFront_(None)
            self.webView.loadHTMLString_baseURL_(loading_html(), None)
            NSApp.activateIgnoringOtherApps_(True)

        def checkServer_(self, timer):
            self.attempts += 1
            try:
                urllib.request.urlopen("http://127.0.0.1:8080", timeout=1)
                timer.invalidate()
                self.window.setTitle_("Vibesbot")
                # Lobby first on the Mac; /login redirects to a broken stub index
                # if ship inflate has not restored templates yet.
                url = NSURL.URLWithString_("http://127.0.0.1:8080/static/lobby.html")
                self.webView.loadRequest_(NSURLRequest.requestWithURL_(url))
            except Exception:
                if self.attempts > 60:
                    timer.invalidate()
                    self.window.setTitle_("VIBESBOT - Error")
                    error_html = """<!DOCTYPE html>
<html><body style="background:#0a0a0a;color:#f07187;font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;text-align:center">
<div>
<p style="font-size:20px;font-weight:600;margin-bottom:12px;color:#f2f2f2">Vibesbot</p>
<p style="font-size:14px">Server failed</p>
<p style="color:#6d6d6d;margin-top:20px;font-size:12px">Check ~/Library/Logs/Vibesbot.log</p>
</div>
</body></html>"""
                    self.webView.loadHTMLString_baseURL_(error_html, None)

        def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
            return True

        def applicationWillTerminate_(self, notification):
            os._exit(0)

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()


if __name__ == "__main__":
    ensure_ship_files()
    free_port()
    time.sleep(0.2)
    main()

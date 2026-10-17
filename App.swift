import Cocoa
import WebKit

final class ControllerLayout: NSView {
    let picture: NSView
    let controls: NSView
    var videoShown = false { didSet { needsLayout=true;layoutSubtreeIfNeeded() } }
    init(picture:NSView,controls:NSView) {
        self.picture=picture;self.controls=controls
        super.init(frame:.zero)
        addSubview(picture);addSubview(controls)
        autoresizingMask=[.width,.height]
    }
    required init?(coder:NSCoder) { fatalError() }
    override func layout() {
        super.layout()
        let controlHeight=videoShown ? min(270,bounds.height) : bounds.height
        controls.frame=NSRect(x:0,y:0,width:bounds.width,height:controlHeight)
        picture.frame=NSRect(x:0,y:controlHeight,width:bounds.width,height:max(0,bounds.height-controlHeight))
        picture.isHidden = !videoShown
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKScriptMessageHandler, WKNavigationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var status: NSStatusItem!
    var activity: NSObjectProtocol?
    var controlProcess: Process?
    var pageReady = false
    var connecting = false
    let video = NativeVideo()
    var readingVideo = false
    var layout: ControllerLayout!
    var controllerFrame: NSRect?
    var videoFrame: NSRect?
    let support = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Roomtone")
    var runtime: [String: Any]? { guard let data = try? Data(contentsOf: support.appendingPathComponent("runtime.json")) else { return nil }; return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        if let icon = Bundle.main.url(forResource: "AppIcon", withExtension: "icns") {
            NSApp.applicationIconImage = NSImage(contentsOf: icon)
        }
        try? FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)
        makeMenu()
        video.onToggleAudio = { [weak self] in self?.toggle() }
        video.onVisibility = { [weak self] visible in self?.setVideoLayout(visible) }
        video.onChange = { [weak self] state in
            guard let self=self else { return }
            if let data=try? JSONSerialization.data(withJSONObject:state),let json=String(data:data,encoding:.utf8) {
                self.web?.evaluateJavaScript("window.nativeVideoChanged?.(\(json))",completionHandler:nil)
            }
            self.api("/api/action",data:state.merging(["action":"nativeVideoStatus"],uniquingKeysWith:{_,new in new}))
        }
        let content = WKUserContentController(); content.add(self, name: "native")
        let config = WKWebViewConfiguration(); config.userContentController = content
        web = WKWebView(frame: .zero, configuration: config); web.navigationDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 760), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Roomtone"; window.minSize = NSSize(width: 390, height: 650); window.maxSize = NSSize(width: 650, height: 1200)
        window.backgroundColor = NSColor(red: 0.098, green: 0.106, blue: 0.102, alpha: 1)
        layout=ControllerLayout(picture:video.surface,controls:web)
        window.appearance = NSAppearance(named: .darkAqua); window.contentView = layout
        window.delegate=self
        window.isReleasedWhenClosed = false; window.setFrameAutosaveName("RoomtoneWindow"); window.center()
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        status = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        status.button?.image = NSImage(systemSymbolName: "hifispeaker.fill", accessibilityDescription: "Roomtone")
        let menu = NSMenu()
        menu.addItem(withTitle: "Open Roomtone", action: #selector(show), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "Play / Pause", action: #selector(toggle), keyEquivalent: "")
        menu.addItem(withTitle: "Volume Up", action: #selector(louder), keyEquivalent: "")
        menu.addItem(withTitle: "Volume Down", action: #selector(quieter), keyEquivalent: "")
        menu.addItem(withTitle: "Reconnect", action: #selector(reconnect), keyEquivalent: "")
        menu.addItem(.separator()); menu.addItem(withTitle: "Quit Roomtone", action: #selector(quit), keyEquivalent: "q")
        for item in menu.items { item.target = self }; status.menu = menu
        ensureServices()
        loadWhenReady(attempt: 0)
        Timer.scheduledTimer(withTimeInterval: 8, repeats: true) { [weak self] _ in self?.updateActivity() }
        Timer.scheduledTimer(withTimeInterval: 0.75, repeats: true) { [weak self] _ in self?.updateVideo() }
    }
    func makeMenu() {
        let main = NSMenu(); let appItem = NSMenuItem(); let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Roomtone", action: #selector(about), keyEquivalent: "").target = self
        appMenu.addItem(.separator()); appMenu.addItem(withTitle: "Hide Roomtone", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "Quit Roomtone", action: #selector(quit), keyEquivalent: "q").target = self
        appItem.submenu = appMenu; main.addItem(appItem)
        let editItem = NSMenuItem(); let edit = NSMenu(title: "Edit")
        for (name, selector, key) in [("Cut", "cut:", "x"),("Copy", "copy:", "c"),("Paste", "paste:", "v"),("Select All", "selectAll:", "a")] { edit.addItem(withTitle: name, action: Selector(selector), keyEquivalent: key) }
        editItem.submenu = edit; main.addItem(editItem); NSApp.mainMenu = main
        let viewItem=NSMenuItem();let viewMenu=NSMenu(title:"View")
        let videoItem=viewMenu.addItem(withTitle:"Show / Hide Video",action:#selector(toggleVideo),keyEquivalent:"v")
        videoItem.keyEquivalentModifierMask=[.command,.shift];videoItem.target=self
        viewItem.submenu=viewMenu;main.addItem(viewItem)
    }
    func ensureServices() {
        // The installed audio helper keeps music playing after the app quits.
        for name in ["media"] {
            let p = Process(); p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
            p.arguments = ["kickstart", "gui/\(getuid())/io.github.daanveerh.roomtone.\(name)"]
            p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice; try? p.run()
        }
    }
    func startControl() {
        guard controlProcess?.isRunning != true else { return }
        let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        p.arguments = [Bundle.main.resourceURL!.appendingPathComponent("service/server.py").path]
        p.environment = ProcessInfo.processInfo.environment.merging(["PATH":"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"], uniquingKeysWith: { _, new in new })
        let log = support.appendingPathComponent("control.log")
        if !FileManager.default.fileExists(atPath: log.path) { FileManager.default.createFile(atPath: log.path, contents: nil) }
        if let handle = try? FileHandle(forWritingTo: log) { handle.seekToEndOfFile(); p.standardOutput = handle; p.standardError = handle }
        try? p.run(); controlProcess = p
    }
    func applicationWillTerminate(_ notification: Notification) { video.player.pause(); controlProcess?.terminate() }
    func setVideoLayout(_ visible:Bool) {
        guard layout != nil,layout.videoShown != visible else { return }
        if !window.styleMask.contains(.fullScreen) {
            if visible {
                controllerFrame=window.frame
                let screen=window.screen?.visibleFrame ?? NSScreen.main!.visibleFrame
                let width=min(960,screen.width)
                let height=min(width*9/16+298,screen.height)
                let frame=videoFrame ?? NSRect(x:min(max(screen.minX,window.frame.midX-width/2),screen.maxX-width),y:min(max(screen.minY,window.frame.maxY-height),screen.maxY-height),width:width,height:height)
                window.minSize=NSSize(width:640,height:480);window.maxSize=NSSize(width:10000,height:10000)
                window.setFrame(frame,display:true,animate:false)
            } else {
                videoFrame=window.frame
                window.minSize=NSSize(width:390,height:650);window.maxSize=NSSize(width:650,height:1200)
                if let frame=controllerFrame { window.setFrame(frame,display:true,animate:false) }
            }
        }
        layout.videoShown=visible
        web.evaluateJavaScript("window.setVideoLayout?.(\(visible ? "true" : "false"))",completionHandler:nil)
        if !visible { window.makeFirstResponder(web) }
    }
    func windowWillClose(_ notification:Notification) { video.hide() }
    @objc func toggleVideo() { video.toggle(); updateVideo() }
    func updateVideo() {
        guard !readingVideo else { return }
        readingVideo=true
        api("/api/video" + (video.desiredVisible ? "?prepare=1" : "")) { [weak self] sample in
            DispatchQueue.main.async {
                guard let self=self else { return };self.readingVideo=false
                if let sample=sample { self.video.consume(sample);self.video.publish() }
                else { self.video.unavailable() }
            }
        }
    }
    func loadWhenReady(attempt: Int) {
        if attempt == 0 { if connecting { return }; connecting = true }
        guard attempt < 30 else { connecting = false; web.loadHTMLString("<body style='background:#191b1a;color:#efede4;font:16px -apple-system;padding:35px'>Roomtone could not start.<br><br>Quit and reopen the app to try again.</body>", baseURL: nil); return }
        api("/api/state") { [weak self] result in
            guard let self = self else { return }
            DispatchQueue.main.async {
                if result != nil, let token = self.runtime?["token"] as? String {
                    self.connecting = false
                    if self.pageReady, let data = try? JSONSerialization.data(withJSONObject: [token]), let encoded = String(data: data, encoding: .utf8) {
                        self.web.evaluateJavaScript("window.reconnectControl(\(encoded)[0])", completionHandler: nil)
                    } else {
                        self.web.load(URLRequest(url: URL(string: "http://127.0.0.1:8776/#\(token)")!))
                    }
                } else { self.startControl(); DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.loadWhenReady(attempt: attempt + 1) } }
            }
        }
    }
    func api(_ path: String, data: [String: Any]? = nil, completion: @escaping ([String: Any]?) -> Void = { _ in }) {
        guard let token = runtime?["token"] as? String else { completion(nil); return }
        var request = URLRequest(url: URL(string: "http://127.0.0.1:8776\(path)")!); request.timeoutInterval = 5
        request.setValue(token, forHTTPHeaderField: "X-Roomtone-Token")
        if let data = data { request.httpMethod = "POST"; request.httpBody = try? JSONSerialization.data(withJSONObject: data); request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        URLSession.shared.dataTask(with: request) { data, response, _ in
            guard let data = data, (response as? HTTPURLResponse)?.statusCode == 200 else { completion(nil); return }
            completion((try? JSONSerialization.jsonObject(with: data)) as? [String: Any])
        }.resume()
    }
    func updateActivity() {
        api("/api/state") { [weak self] state in DispatchQueue.main.async {
            guard let self = self else { return }; if state == nil { self.startControl(); self.loadWhenReady(attempt: 0) }; let playing = state?["playing"] as? Bool == true && state?["connected"] as? Bool == true
            if playing && self.activity == nil { self.activity = ProcessInfo.processInfo.beginActivity(options: [.idleSystemSleepDisabled], reason: "Streaming local music to Sonos") }
            if !playing, let activity = self.activity { ProcessInfo.processInfo.endActivity(activity); self.activity = nil }
        } }
    }
    @objc func about() {
        var options: [NSApplication.AboutPanelOptionKey: Any] = [:]
        if let url = Bundle.main.url(forResource: "AppIcon", withExtension: "icns"), let icon = NSImage(contentsOf: url) {
            options[.applicationIcon] = icon
        }
        NSApp.orderFrontStandardAboutPanel(options: options)
    }
    @objc func show() { window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }
    @objc func toggle() { api("/api/state") { [weak self] s in guard let s = s else { return }; self?.api("/api/action", data: ["action": s["playing"] as? Bool == true ? "pause" : "play"]) } }
    func volume(_ change: Int) { api("/api/state") { [weak self] s in guard let v = s?["volume"] as? Int else { return }; self?.api("/api/action", data: ["action":"volume", "value": max(0,min(100,v+change))]) } }
    @objc func louder() { volume(2) }
    @objc func quieter() { volume(-2) }
    @objc func reconnect() { ensureServices(); api("/api/action", data: ["action":"reconnect"]); loadWhenReady(attempt: 0) }
    @objc func quit() { NSApp.terminate(nil) }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { show(); return true }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, message.frameInfo.securityOrigin.host == "127.0.0.1", let body = message.body as? [String: Any], let action = body["action"] as? String else { return }
        if action == "reconnect" { ensureServices(); startControl(); loadWhenReady(attempt: 0) }
        if action == "pin" { window.level = body["value"] as? Bool == true ? .floating : .normal }
        if action == "toggleVideo" { toggleVideo() }
        if action == "showVideo" { video.show();updateVideo() }
        if action == "hideVideo" { video.hide() }
        if action == "folder" {
            let panel = NSOpenPanel(); panel.canChooseFiles = false; panel.canChooseDirectories = true; panel.allowsMultipleSelection = false; panel.prompt = "Add music folder"
            panel.beginSheetModal(for: window) { response in
                if response == .OK, let path = panel.url?.path, let data = try? JSONSerialization.data(withJSONObject: [path]), let encoded = String(data: data, encoding: .utf8) { self.web.evaluateJavaScript("window.addMusicFolder(\(encoded)[0])", completionHandler: nil) }
            }
        }
        if action == "openURL", let value = body["url"] as? String, let url = URL(string: value), url.scheme == "https", url.host == "support.sonos.com" { NSWorkspace.shared.open(url) }
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        pageReady = true
        web.evaluateJavaScript("window.setVideoLayout?.(\(layout.videoShown ? "true" : "false"))",completionHandler:nil)
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { pageReady = false; loadWhenReady(attempt: 0) }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { pageReady = false; loadWhenReady(attempt: 0) }
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        decisionHandler(url.host == "127.0.0.1" && url.port == 8776 ? .allow : .cancel)
    }
}
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()

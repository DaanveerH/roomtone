import Cocoa
import AVFoundation

// A retained native player: hiding never destroys the item or stops Sonos.
final class VideoSurface: NSView {
    let videoLayer = AVPlayerLayer()
    let message = NSTextField(labelWithString: "Preparing video…")
    var hide: (() -> Void)?
    var toggleAudio: (() -> Void)?
    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true; layer?.backgroundColor = NSColor.black.cgColor
        videoLayer.videoGravity = .resizeAspect; layer?.addSublayer(videoLayer)
        message.textColor = .lightGray; message.alignment = .center
        message.font = .systemFont(ofSize: 13); addSubview(message)
        setAccessibilityLabel("Silent video. Sound plays on Sonos.")
    }
    required init?(coder: NSCoder) { fatalError() }
    override var acceptsFirstResponder: Bool { true }
    override func layout() {
        super.layout()
        CATransaction.begin(); CATransaction.setDisableActions(true)
        videoLayer.frame = bounds; CATransaction.commit()
        message.frame = NSRect(x: 20, y: bounds.midY-12, width: max(0,bounds.width-40), height: 24)
    }
    override func keyDown(with event: NSEvent) {
        if event.keyCode == 53 || event.charactersIgnoringModifiers == "v" { hide?() }
        else if event.charactersIgnoringModifiers == " " { toggleAudio?() }
        else if event.charactersIgnoringModifiers == "f" { window?.toggleFullScreen(nil) }
        else { super.keyDown(with: event) }
    }
    override func mouseDown(with event: NSEvent) {
        if event.clickCount == 2 { window?.toggleFullScreen(nil) }
        else { super.mouseDown(with:event) }
    }
}

struct SpeakerVideoSample {
    let id: String
    let path: String
    let title: String
    let position: Double
    let sampled: Double
    let playing: Bool
    let offset: Double
    var target: Double {
        max(0, position + offset + (playing ? max(0,Date().timeIntervalSince1970-sampled) : 0))
    }
}

final class NativeVideo: NSObject {
    let player = AVPlayer()
    let surface = VideoSurface(frame: NSRect(x:0,y:0,width:800,height:450))
    var onVisibility: ((Bool) -> Void)?
    var onChange: (([String:Any]) -> Void)?
    var onToggleAudio: (() -> Void)?
    var latest: SpeakerVideoSample?
    var desiredVisible = false
    var ready = false
    var error = ""
    var path = ""
    var generation = 0
    var loads = 0
    var seeking = false
    var lastSampleAt = Date.distantPast
    var itemObservation: NSKeyValueObservation?
    var frameObservation: NSKeyValueObservation?
    var lastRequest = 0
    var showStarted: CFTimeInterval = 0
    var showMilliseconds: Double = 0
    var frameMilliseconds: Double = 0

    override init() {
        super.init()
        player.isMuted = true; player.volume = 0
        player.automaticallyWaitsToMinimizeStalling = false
        player.preventsDisplaySleepDuringVideoPlayback = false
        surface.videoLayer.player = player
        surface.isHidden = true
        surface.hide = { [weak self] in self?.hide() }
        surface.toggleAudio = { [weak self] in self?.onToggleAudio?() }
        frameObservation = surface.videoLayer.observe(\.isReadyForDisplay,options:[.new]) { [weak self] _,_ in
            DispatchQueue.main.async { self?.refreshFrame() }
        }
    }
    var state: [String:Any] {
        ["active":desiredVisible,"visible":desiredVisible && !surface.isHidden && surface.window?.isVisible == true,"ready":ready,
         "id":latest?.id ?? "","message":error.isEmpty ? (desiredVisible ? "Sound on Sonos · Esc to hide" : "Video ready · sound on Sonos") : error,
         "muted":player.isMuted,"volume":player.volume,"position":player.currentTime().seconds.isFinite ? player.currentTime().seconds : 0,
         "rate":player.rate,"loads":loads,"sampled":Date().timeIntervalSince1970,
         "enabledAudioTracks":player.currentItem?.tracks.filter { $0.isEnabled && $0.assetTrack?.mediaType == .audio }.count ?? 0,
         "showMilliseconds":showMilliseconds,"frameMilliseconds":frameMilliseconds]
    }
    func publish() { onChange?(state) }
    func refreshFrame() {
        surface.message.isHidden = surface.videoLayer.isReadyForDisplay && error.isEmpty
        if desiredVisible && surface.videoLayer.isReadyForDisplay && showStarted > 0 {
            frameMilliseconds = (CACurrentMediaTime()-showStarted)*1000; showStarted = 0
        }
        publish()
    }
    func toggle() { desiredVisible ? hide() : show() }
    func show() {
        let started = CACurrentMediaTime(); showStarted = started
        desiredVisible = true
        surface.isHidden = false; onVisibility?(true)
        surface.window?.makeKeyAndOrderFront(nil); surface.window?.makeFirstResponder(surface)
        synchronize(force:true)
        showMilliseconds = (CACurrentMediaTime()-started)*1000
        if !ready { surface.message.stringValue = error.isEmpty ? "Preparing video…" : error; surface.message.isHidden = false }
        publish()
    }
    func hide() {
        desiredVisible = false; showStarted = 0
        surface.isHidden = true; onVisibility?(false)
        player.pause(); publish()
    }
    func unavailable() {
        player.pause()
        if Date().timeIntervalSince(lastSampleAt)>2 {
            error = "Waiting for Sonos…"; surface.message.stringValue=error; surface.message.isHidden=false; publish()
        }
    }
    func consume(_ data:[String:Any]) {
        lastSampleAt = Date()
        guard let identity=data["id"] as? String, !identity.isEmpty else {
            latest=nil; ready=false; path=""; generation+=1; itemObservation=nil
            player.replaceCurrentItem(with:nil); hide(); return
        }
        let next = SpeakerVideoSample(id:identity,path:data["path"] as? String ?? "",title:data["title"] as? String ?? "Video",position:data["position"] as? Double ?? 0,sampled:data["sampled"] as? Double ?? Date().timeIntervalSince1970,playing:data["playing"] as? Bool ?? false,offset:data["offset"] as? Double ?? 0)
        let changedIdentity = latest?.id != identity
        latest = next
        let request = data["request"] as? Int ?? 0
        if request != lastRequest {
            lastRequest=request
            if data["requestedId"] as? String == identity { desiredVisible=true }
        }
        if changedIdentity { player.pause() }
        if next.path.isEmpty {
            error=data["message"] as? String ?? "Preparing video…"
            if changedIdentity { generation+=1; path=""; ready=false; player.replaceCurrentItem(with:nil) }
            surface.message.stringValue=error; surface.message.isHidden=false
            if desiredVisible && surface.isHidden { show() }
            publish(); return
        }
        if path != next.path { load(next) }
        else if error == "Waiting for Sonos…" { error=""; refreshFrame() }
        if desiredVisible && surface.isHidden { show() }
        synchronize()
    }
    func load(_ sample:SpeakerVideoSample) {
        path=sample.path; generation+=1; let version=generation
        loads+=1; ready=false; error=""; seeking=false
        player.pause(); player.isMuted=true; player.volume=0
        surface.message.stringValue="Preparing video…"; surface.message.isHidden=false
        let item=AVPlayerItem(url:URL(fileURLWithPath:sample.path))
        itemObservation=nil; player.replaceCurrentItem(with:item)
        itemObservation=item.observe(\.status,options:[.initial,.new]) { [weak self] item,_ in
            DispatchQueue.main.async {
                guard let self=self, self.generation==version else { return }
                if item.status == .readyToPlay {
                    // No audio track can play, even if the player mute is changed later.
                    for track in item.tracks where track.assetTrack?.mediaType == .audio { track.isEnabled=false }
                    self.ready=true; self.error=""; self.synchronize(force:true,prewarm:true); self.publish()
                } else if item.status == .failed {
                    self.error="This video format cannot play in the built-in player."
                    self.surface.message.stringValue=self.error; self.surface.message.isHidden=false; self.publish()
                }
            }
        }
    }
    func synchronize(force:Bool=false,prewarm:Bool=false) {
        guard ready,let sample=latest, !seeking else { return }
        if Date().timeIntervalSince(lastSampleAt)>2 { player.pause(); return }
        if !desiredVisible && !prewarm { player.pause(); return }
        let target=sample.target
        let current=player.currentTime().seconds
        let tolerance=sample.playing ? 1.25 : 0.2
        if force || !current.isFinite || abs(current-target)>tolerance {
            seeking=true; let version=generation
            player.seek(to:CMTime(seconds:target,preferredTimescale:600),toleranceBefore:.zero,toleranceAfter:.zero) { [weak self] _ in
                DispatchQueue.main.async {
                    guard let self=self,self.generation==version else { return }
                    self.seeking=false
                    if self.desiredVisible && self.latest?.playing == true && Date().timeIntervalSince(self.lastSampleAt)<2 { self.player.playImmediately(atRate:1) }
                    else { self.player.pause() }
                    self.refreshFrame()
                }
            }
        } else if desiredVisible && sample.playing { player.playImmediately(atRate:1) }
        else { player.pause() }
    }
}

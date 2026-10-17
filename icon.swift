// Original vector icon. Build assets locally; no bundled artwork or image libraries.
import AppKit
let root = URL(fileURLWithPath: CommandLine.arguments[1]).appendingPathComponent("Roomtone.iconset")
try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
        let transform = NSAffineTransform(); transform.scale(by: CGFloat(pixels)/1024); transform.concat()
        NSColor(calibratedRed: 0.14, green: 0.17, blue: 0.13, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: 80, y: 80, width: 864, height: 864), xRadius: 200, yRadius: 200).fill()
        NSColor(calibratedRed: 0.83, green: 0.89, blue: 0.67, alpha: 1).setStroke()
        for radius: CGFloat in [135, 245, 350] {
            let circle = NSBezierPath(ovalIn: NSRect(x: 512-radius, y: 512-radius, width: radius*2, height: radius*2))
            circle.lineWidth = 30; circle.stroke()
        }
        NSColor(calibratedRed: 0.83, green: 0.89, blue: 0.67, alpha: 1).setFill()
        NSBezierPath(ovalIn: NSRect(x: 467, y: 467, width: 90, height: 90)).fill()
        NSGraphicsContext.restoreGraphicsState()
        let suffix = scale == 2 ? "@2x" : ""
        try bitmap.representation(using: .png, properties: [:])!.write(to: root.appendingPathComponent("icon_\(size)x\(size)\(suffix).png"))
    }
}

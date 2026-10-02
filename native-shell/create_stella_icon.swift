import AppKit
import Foundation

guard CommandLine.arguments.count == 3,
      let source = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: 1024,
        pixelsHigh: 1024,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
      ),
      let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
    fatalError("无法创建 Stella 应用图标")
}

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = context
context.imageInterpolation = .high

let tile = NSRect(x: 36, y: 36, width: 952, height: 952)
let shadow = NSShadow()
shadow.shadowBlurRadius = 18
shadow.shadowOffset = NSSize(width: 0, height: -7)
shadow.shadowColor = NSColor.black.withAlphaComponent(0.16)
shadow.set()
NSColor.white.setFill()
NSBezierPath(roundedRect: tile, xRadius: 206, yRadius: 206).fill()

// 原始透明图保留完整字形；只在图标画布中加入明亮底板。
shadow.shadowColor = .clear
shadow.set()
source.draw(in: NSRect(x: 0, y: 0, width: 1024, height: 1024))
NSGraphicsContext.restoreGraphicsState()

guard let png = bitmap.representation(using: .png, properties: [:]) else {
    fatalError("无法导出 Stella 应用图标")
}
try png.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))

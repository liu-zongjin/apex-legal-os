import Foundation
import ImageIO
import Vision

let imageData = FileHandle.standardInput.readDataToEndOfFile()
guard let source = CGImageSourceCreateWithData(imageData as CFData, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    exit(1)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true

do {
    try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
    var items: [[String: Any]] = []
    for result in request.results ?? [] {
        guard let observation = result as? VNRecognizedTextObservation,
              let candidate = observation.topCandidates(1).first else { continue }
        let box = observation.boundingBox
        items.append([
            "text": candidate.string,
            "x": box.minX,
            // Vision 坐标原点在左下；转换为从上向下，便于 Python 归并成表格行。
            "y": 1 - box.maxY,
            "height": box.height,
        ])
    }
    let json = try JSONSerialization.data(withJSONObject: ["items": items])
    FileHandle.standardOutput.write(json)
} catch {
    exit(1)
}

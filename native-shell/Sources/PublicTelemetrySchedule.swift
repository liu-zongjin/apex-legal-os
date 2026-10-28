import Foundation

// Shared, deterministic rules for the public Mac sender. The caller persists
// each reservation before starting an HTTP request, including failed attempts.
struct PublicTelemetrySchedule {
    static let interval: TimeInterval = 21_600

    static func canSend(consented: Bool, now: TimeInterval, lastAttempt: TimeInterval) -> Bool {
        consented && (lastAttempt <= 0 || now - lastAttempt >= interval)
    }

    static func nextDelay(now: TimeInterval, lastAttempt: TimeInterval) -> TimeInterval {
        guard lastAttempt > 0 else { return 1 }
        return max(1, lastAttempt + interval - now)
    }
}

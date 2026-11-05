import Foundation

// Shared, deterministic rules for the public Mac sender. The caller persists
// each reservation before starting an HTTP request, including failed attempts.
struct PublicTelemetrySchedule {
    static func isEnabled(storedPreference: Bool?) -> Bool {
        storedPreference ?? true
    }

    static let interval: TimeInterval = 21_600

    static func canSend(consented: Bool, now: TimeInterval, lastAttempt: TimeInterval, delay: TimeInterval = interval) -> Bool {
        consented && (lastAttempt <= 0 || now - lastAttempt >= delay)
    }

    static func nextDelay(now: TimeInterval, lastAttempt: TimeInterval, delay: TimeInterval = interval) -> TimeInterval {
        guard lastAttempt > 0 else { return 1 }
        return max(1, lastAttempt + delay - now)
    }
}

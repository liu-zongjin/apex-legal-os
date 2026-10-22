import Foundation

enum UpdateInstallationPolicy {
    static func isSourceWorkspace(_ info: [String: Any]) -> Bool {
        let frontend = (info["LegalKBFrontendPath"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        // Unknown/legacy identities fail closed instead of accepting a package
        // that could switch the user's backend and local data directory.
        return !frontend.isEmpty || info["CFBundleIdentifier"] as? String != "com.stella.public.native"
    }
}

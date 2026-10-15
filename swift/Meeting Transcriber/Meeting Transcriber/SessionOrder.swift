import Foundation

/// The saved manual order of Dynamic and Fixed sessions.
nonisolated struct SessionOrder: Decodable, Sendable {
    let dynamic: [String]
    let fixed: [String]

    static let empty = SessionOrder(dynamic: [], fixed: [])
}

import SwiftUI

/// How much room each row in the Meetings list takes.
enum MeetingDensity: String, CaseIterable, Identifiable {
    case compact
    case normal
    case roomy

    var id: String {
        rawValue
    }

    var label: String {
        switch self {
        case .compact:
            return "Compact"
        case .normal:
            return "Normal"
        case .roomy:
            return "Roomy"
        }
    }

    /// Space between the title line and the date/people line.
    var lineSpacing: CGFloat {
        switch self {
        case .compact:
            return 0
        case .normal:
            return 4
        case .roomy:
            return 6
        }
    }

    /// Space above and below each row.
    var rowPadding: CGFloat {
        switch self {
        case .compact:
            return 1
        case .normal:
            return 4
        case .roomy:
            return 9
        }
    }

    var detailFont: Font {
        switch self {
        case .compact:
            return .caption2
        case .normal:
            return .caption
        case .roomy:
            return .caption
        }
    }
}

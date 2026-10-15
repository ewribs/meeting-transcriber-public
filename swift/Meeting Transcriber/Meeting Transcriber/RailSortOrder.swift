import Foundation

/// How folders and sessions are ordered in the Meetings sidebar.
/// A–Z sorts by name; Manual follows the order saved by dragging.
enum RailSortOrder: String, CaseIterable, Identifiable {
    case alpha
    case manual

    var id: String {
        rawValue
    }

    var label: String {
        switch self {
        case .alpha:
            return "A–Z"
        case .manual:
            return "Manual (drag to reorder)"
        }
    }

    /// `manualOrder` is the saved name order. Items it does not list
    /// keep their existing relative order after the listed ones. An empty
    /// list leaves the items exactly as given.
    func sorted<T>(
        _ items: [T],
        name: (T) -> String,
        manualOrder: [String] = []
    ) -> [T] {
        switch self {
        case .alpha:
            return items.sorted { first, second in
                name(first).localizedStandardCompare(name(second))
                    == .orderedAscending
            }
        case .manual:
            if manualOrder.isEmpty {
                return items
            }

            var byName: [String: T] = [:]

            for item in items {
                byName[name(item)] = item
            }

            var result: [T] = []
            var used = Set<String>()

            for listed in manualOrder {
                if let item = byName[listed], !used.contains(listed) {
                    result.append(item)
                    used.insert(listed)
                }
            }

            for item in items where !used.contains(name(item)) {
                result.append(item)
            }

            return result
        }
    }

    /// Moves `item` into the slot `target` occupies: dragging down puts
    /// it after the target, dragging up puts it before.
    static func moved(
        _ names: [String],
        item: String,
        onto target: String
    ) -> [String] {
        guard let from = names.firstIndex(of: item),
              let to = names.firstIndex(of: target),
              from != to
        else {
            return names
        }

        var result = names
        result.remove(at: from)
        result.insert(item, at: to)
        return result
    }
}

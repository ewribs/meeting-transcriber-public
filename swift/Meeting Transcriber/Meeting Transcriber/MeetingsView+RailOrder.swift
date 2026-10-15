import SwiftUI

/// Drag-to-reorder for folders and sessions in the Meetings sidebar.
/// A reorder drag carries "railorder:<kind>:<name>" so it can never be
/// mistaken for meetings being dropped onto a folder or session.
extension MeetingsView {
    static let railOrderPrefix = "railorder:"

    func railOrderPayload(
        kind: String,
        name: String
    ) -> String {
        Self.railOrderPrefix + kind + ":" + name
    }

    func parseRailOrder(
        _ payloads: [String]
    ) -> (kind: String, name: String)? {
        for payload in payloads
        where payload.hasPrefix(Self.railOrderPrefix) {
            let rest: String = String(
                payload.dropFirst(Self.railOrderPrefix.count)
            )

            if let colon = rest.firstIndex(of: ":") {
                let kind: String = String(rest[..<colon])
                let name: String = String(
                    rest[rest.index(after: colon)...]
                )
                return (kind, name)
            }
        }

        return nil
    }

    func orderedFolderNames() -> [String] {
        railSort
            .sorted(folders, name: { $0.name })
            .map { $0.name }
    }

    func sessionsOfKind(_ kind: String) -> [SavedSession] {
        allSessions.filter { $0.isDynamic == (kind == "dynamic") }
    }

    func savedSessionOrder(_ kind: String) -> [String] {
        kind == "dynamic" ? sessionOrder.dynamic : sessionOrder.fixed
    }

    func orderedSessionNames(_ kind: String) -> [String] {
        railSort
            .sorted(
                sessionsOfKind(kind),
                name: { $0.name },
                manualOrder: savedSessionOrder(kind)
            )
            .map { $0.name }
    }

    /// True when the drop was a sidebar reorder of this kind.
    func handleRailOrderDrop(
        _ payloads: [String],
        kind: String,
        onto target: String
    ) -> Bool {
        guard let dragged = parseRailOrder(payloads),
              dragged.kind == kind
        else {
            return false
        }

        Task {
            await moveRailItem(
                kind: kind,
                name: dragged.name,
                onto: target
            )
        }

        return true
    }

    @MainActor
    func moveRailItem(
        kind: String,
        name: String,
        onto target: String
    ) async {
        if name == target {
            return
        }

        let current: [String] = kind == "folder"
            ? orderedFolderNames()
            : orderedSessionNames(kind)

        let updated: [String] = RailSortOrder.moved(
            current,
            item: name,
            onto: target
        )

        if updated == current {
            return
        }

        do {
            // Leaving A–Z: keep every group exactly as it looks now,
            // so only the dragged group changes.
            if railSort == .alpha {
                try await adoptCurrentOrder()
            }

            if kind == "folder" {
                folders = try await backend
                    .reorderFolders(names: updated)
            } else {
                sessionOrder = try await backend.saveSessionOrder(
                    kind: kind,
                    names: updated
                )
            }

            railSortRaw = "manual"
        } catch {
            addToSessionTitle = "Couldn't Reorder"
            addToSessionResult = error.localizedDescription
        }
    }

    @MainActor
    func adoptCurrentOrder() async throws {
        let folderNames: [String] = orderedFolderNames()
        let dynamicNames: [String] = orderedSessionNames("dynamic")
        let fixedNames: [String] = orderedSessionNames("fixed")

        folders = try await backend.reorderFolders(
            names: folderNames
        )

        _ = try await backend.saveSessionOrder(
            kind: "dynamic",
            names: dynamicNames
        )

        sessionOrder = try await backend.saveSessionOrder(
            kind: "fixed",
            names: fixedNames
        )
    }
}
